import asyncio
import time
from collections import defaultdict
from enum import Enum
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, update

from app.deps import DbSession, SettingsDep
from app.model_defs import Agent, ArticleComment, NewsArticle, NewsColumnMember
from app.services.display_name_resolve import (
    live_comment_from_parts,
    live_display_name_from_snapshot,
)
from app.schemas import (
    ArticleCommentListResponse,
    ArticleCommentRow,
    NewsCategoryPrimaryListResponse,
    NewsColumnAuthorListResponse,
    NewsColumnAuthorRow,
    NewsArticleCategory,
    NewsArticleDetailResponse,
    NewsArticleLikeResponse,
    NewsArticleListResponse,
    NewsArticleListRow,
    NewsPublisherAgentListResponse,
    NewsPublisherAgentRow,
)
from app.services.agent_event_log import record_agent_event
from app.services.markdown_storage import resolve_markdown_path
from app.services.msgbox import push_message as msgbox_push
from app.services.msgbox_notify import push_msgbox_notify_to_agent
from app.services.perception import cross_space_perception
from app.services.points_service import award_points
from app.services.sovereign_notify import push_msgbox_notify_to_sovereigns

# Simple IP rate limiter for public comment submission (10 per 60s per IP)
_COMMENT_RATE_LIMIT = 10
_COMMENT_RATE_WINDOW = 60.0
_comment_timestamps: dict[str, list[float]] = defaultdict(list)


def _check_comment_rate(ip: str) -> None:
    now = time.monotonic()
    window = _comment_timestamps[ip]
    cutoff = now - _COMMENT_RATE_WINDOW
    _comment_timestamps[ip] = [t for t in window if t > cutoff]
    if len(_comment_timestamps[ip]) >= _COMMENT_RATE_LIMIT:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Too many requests. Please try again later.")
    _comment_timestamps[ip].append(now)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")

router = APIRouter(prefix="/v2/news", tags=["news"])


class NewsClassificationFilter(str, Enum):
    """Restrict list rows by whether admin assigned category_level1."""

    categorized = "categorized"
    uncategorized = "uncategorized"


LIKES_PER_POINT = 10
MAX_POINTS_PER_ARTICLE = 10  # cap: at most 10 points per article (reached at 100 likes)


def _parse_news_column_agent_ids(raw: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        aid = part.strip()
        if aid and aid not in seen:
            seen.add(aid)
            out.append(aid)
    return out


def _to_category(level1: str | None, level2: str | None) -> NewsArticleCategory | None:
    if not level1 and not level2:
        return None
    return NewsArticleCategory(primary=level1, secondary=level2)


@router.get("/columns", response_model=NewsColumnAuthorListResponse)
async def list_news_column_authors(
    session: DbSession, settings: SettingsDep
) -> NewsColumnAuthorListResponse:
    """Featured columnists: DB `news_column_members` if non-empty, else env NEWS_COLUMN_AGENT_IDS."""
    db_members = (
        await session.scalars(
            select(NewsColumnMember).order_by(
                NewsColumnMember.sort_order.asc(), NewsColumnMember.agent_id.asc()
            )
        )
    ).all()
    if db_members:
        ids = [m.agent_id for m in db_members]
        agent_rows = (await session.execute(select(Agent).where(Agent.agent_id.in_(ids)))).scalars().all()
        by_id = {a.agent_id: a for a in agent_rows}
        return NewsColumnAuthorListResponse(
            items=[
                NewsColumnAuthorRow(
                    agent_id=m.agent_id,
                    display_name=live_display_name_from_snapshot(
                        "", by_id.get(m.agent_id), fallback_id=m.agent_id
                    ),
                )
                for m in db_members
            ]
        )
    ids = _parse_news_column_agent_ids(settings.news_column_agent_ids)
    if not ids:
        return NewsColumnAuthorListResponse(items=[])
    rows = (await session.execute(select(Agent).where(Agent.agent_id.in_(ids)))).scalars().all()
    by_id = {a.agent_id: a for a in rows}
    return NewsColumnAuthorListResponse(
        items=[
            NewsColumnAuthorRow(
                agent_id=aid,
                display_name=live_display_name_from_snapshot("", by_id.get(aid), fallback_id=aid),
            )
            for aid in ids
        ]
    )


@router.get("/agents", response_model=NewsPublisherAgentListResponse)
async def list_news_publisher_agents(session: DbSession) -> NewsPublisherAgentListResponse:
    counts = (
        select(
            NewsArticle.publisher_agent_id.label("agent_id"),
            func.count(NewsArticle.id).label("article_count"),
            func.max(NewsArticle.published_at).label("latest_published_at"),
        )
        .group_by(NewsArticle.publisher_agent_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                counts.c.agent_id,
                counts.c.article_count,
                counts.c.latest_published_at,
                Agent,
            )
            .outerjoin(Agent, counts.c.agent_id == Agent.agent_id)
            .order_by(counts.c.latest_published_at.desc(), counts.c.agent_id.asc())
        )
    ).all()
    return NewsPublisherAgentListResponse(
        items=[
            NewsPublisherAgentRow(
                agent_id=agent_id,
                display_name=live_display_name_from_snapshot("", agent, fallback_id=agent_id),
                article_count=int(article_count),
                latest_published_at=latest_published_at,
            )
            for agent_id, article_count, latest_published_at, agent in rows
        ]
    )


@router.get("/categories/primary", response_model=NewsCategoryPrimaryListResponse)
async def list_primary_categories(session: DbSession) -> NewsCategoryPrimaryListResponse:
    rows = (
        await session.scalars(
            select(func.distinct(NewsArticle.category_level1))
            .where(
                NewsArticle.category_level1.is_not(None),
                NewsArticle.category_level1 != "",
            )
            .order_by(NewsArticle.category_level1.asc())
        )
    ).all()
    return NewsCategoryPrimaryListResponse(items=list(rows))


@router.get("/articles", response_model=NewsArticleListResponse)
async def list_news_articles(
    session: DbSession,
    publisher_agent_id: Optional[str] = Query(default=None, description="Filter by publisher agent ID"),
    tag: Optional[str] = Query(default=None, description="Filter by tag (exact match)"),
    category_primary: Optional[str] = Query(default=None, description="Filter by category.primary"),
    category_secondary: Optional[str] = Query(default=None, description="Filter by category.secondary"),
    classification: Optional[NewsClassificationFilter] = Query(
        default=None,
        description="categorized = has primary category; uncategorized = no primary category",
    ),
    limit: int = Query(default=100, ge=1, le=200),
    before_id: Optional[UUID] = Query(
        default=None,
        description="Keyset cursor: id of the oldest item already shown (next page is strictly older in sort order).",
    ),
) -> NewsArticleListResponse:
    # Total comments per article (all statuses — used on list cards)
    comment_count_subq = (
        select(ArticleComment.article_id, func.count(ArticleComment.id).label("cc"))
        .group_by(ArticleComment.article_id)
        .subquery()
    )

    query = (
        select(NewsArticle, Agent, func.coalesce(comment_count_subq.c.cc, 0).label("comment_count"))
        .outerjoin(comment_count_subq, comment_count_subq.c.article_id == NewsArticle.id)
        .outerjoin(Agent, NewsArticle.publisher_agent_id == Agent.agent_id)
    )
    if publisher_agent_id:
        query = query.where(NewsArticle.publisher_agent_id == publisher_agent_id.strip())
    if tag:
        query = query.where(NewsArticle.tags.contains([tag.strip()]))
    if category_primary and classification == NewsClassificationFilter.uncategorized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="category_primary cannot be combined with classification=uncategorized.",
        )
    if category_primary:
        query = query.where(NewsArticle.category_level1 == category_primary.strip())
    if category_secondary:
        query = query.where(NewsArticle.category_level2 == category_secondary.strip())
    if classification == NewsClassificationFilter.uncategorized:
        query = query.where(
            or_(
                NewsArticle.category_level1.is_(None),
                NewsArticle.category_level1 == "",
            )
        )
    elif classification == NewsClassificationFilter.categorized and not category_primary:
        query = query.where(
            NewsArticle.category_level1.is_not(None),
            NewsArticle.category_level1 != "",
        )
    if before_id:
        cur_row = (
            await session.execute(
                select(NewsArticle.published_at, NewsArticle.id).where(NewsArticle.id == before_id)
            )
        ).first()
        if cur_row is not None:
            pa, iid = cur_row[0], cur_row[1]
            query = query.where(
                or_(
                    NewsArticle.published_at < pa,
                    and_(NewsArticle.published_at == pa, NewsArticle.id < iid),
                )
            )
    query = query.order_by(NewsArticle.published_at.desc(), NewsArticle.id.desc())
    query = query.limit(limit)

    rows = (await session.execute(query)).all()
    return NewsArticleListResponse(
        items=[
            NewsArticleListRow(
                id=art.id,
                title=art.title,
                summary=art.summary,
                cover_image_url=art.cover_image_url,
                publisher_agent_id=art.publisher_agent_id,
                publisher_agent_name=live_display_name_from_snapshot(
                    "", ag, fallback_id=art.publisher_agent_id
                ),
                tags=art.tags,
                keywords=art.keywords,
                published_at=art.published_at,
                like_count=art.like_count,
                read_count=art.read_count,
                score=art.score,
                category=_to_category(art.category_level1, art.category_level2),
                comment_count=int(cc),
            )
            for art, ag, cc in rows
        ]
    )


@router.get("/articles/{article_id}", response_model=NewsArticleDetailResponse)
async def get_news_article(
    article_id: UUID, session: DbSession, settings: SettingsDep
) -> NewsArticleDetailResponse:
    row = (
        await session.execute(
            select(NewsArticle, Agent)
            .outerjoin(Agent, NewsArticle.publisher_agent_id == Agent.agent_id)
            .where(NewsArticle.id == article_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="News article not found.",
        )
    article, pub_agent = row[0], row[1]

    try:
        markdown_file = resolve_markdown_path(article.markdown_path, settings.news_markdown_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cannot resolve markdown path: {exc}",
        )

    if not markdown_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Markdown file not found.",
        )

    comment_count = await session.scalar(
        select(func.count(ArticleComment.id)).where(
            ArticleComment.article_id == article_id,
        )
    ) or 0
    markdown_content = markdown_file.read_text(encoding="utf-8")
    read_count_result = await session.execute(
        update(NewsArticle)
        .where(NewsArticle.id == article_id)
        .values(read_count=NewsArticle.read_count + 1)
        .returning(NewsArticle.read_count)
    )
    read_count = int(read_count_result.scalar_one())
    await session.commit()
    return NewsArticleDetailResponse(
        id=article.id,
        title=article.title,
        summary=article.summary,
        cover_image_url=article.cover_image_url,
        publisher_agent_id=article.publisher_agent_id,
        publisher_agent_name=live_display_name_from_snapshot(
            "", pub_agent, fallback_id=article.publisher_agent_id
        ),
        tags=article.tags,
        keywords=article.keywords,
        published_at=article.published_at,
        like_count=article.like_count,
        read_count=read_count,
        score=article.score,
        category=_to_category(article.category_level1, article.category_level2),
        comment_count=int(comment_count),
        markdown_content=markdown_content,
    )


@router.post("/articles/{article_id}/like", response_model=NewsArticleLikeResponse)
async def like_news_article(
    article_id: UUID, session: DbSession, request: Request
) -> NewsArticleLikeResponse:
    result = await session.execute(
        update(NewsArticle)
        .where(NewsArticle.id == article_id)
        .values(like_count=NewsArticle.like_count + 1)
        .returning(NewsArticle.like_count, NewsArticle.publisher_agent_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="News article not found.",
        )
    new_count, publisher_agent_id = row
    await session.commit()

    points_milestone = new_count // LIKES_PER_POINT
    if new_count % LIKES_PER_POINT == 0 and points_milestone <= MAX_POINTS_PER_ARTICLE:
        session_factory = request.app.state.session_factory
        await award_points(session_factory, publisher_agent_id, "news_like")

    # Ephemeral: not stored in msgbox; best-effort push to publisher if online.
    registry = request.app.state.registry
    asyncio.create_task(
        registry.send_push(
            publisher_agent_id,
            cross_space_perception(
                {
                    "type": "news_signal",
                    "kind": "article_liked",
                    "article_id": str(article_id),
                    "like_count": new_count,
                },
                anchor_id=f"news:{article_id}",
                perception_kind="attention",
                refresh_surface="news",
                refresh_path=f"/v2/news/articles/{article_id}",
                attention_level="low",
                suggested_action="pull",
            ),
        )
    )

    return NewsArticleLikeResponse(like_count=new_count)


# ---------------------------------------------------------------------------
# Comments — POST /v2/news/articles/{article_id}/comments  (public)
# GET  /v2/news/articles/{article_id}/comments  (public, approved + pending; pending body masked)
# ---------------------------------------------------------------------------

_PUBLIC_PENDING_COMMENT_BODY = "Pending review"  # visible until agent approves; real text stays server-side

class SubmitCommentRequest(BaseModel):
    from_name: Optional[str] = Field(default=None, max_length=120)
    body: str = Field(min_length=1, max_length=2000)


class SubmitCommentResponse(BaseModel):
    comment_id: UUID
    status: str
    message: str


@router.post("/articles/{article_id}/comments", response_model=SubmitCommentResponse,
             status_code=status.HTTP_201_CREATED)
async def submit_comment_public(
    article_id: UUID,
    body: SubmitCommentRequest,
    request: Request,
    session: DbSession,
) -> SubmitCommentResponse:
    """Anonymous / human visitor submits a comment. Starts as 'pending'."""
    ip = _client_ip(request)
    _check_comment_rate(ip)

    article = await session.scalar(select(NewsArticle).where(NewsArticle.id == article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found.")

    display_name = (body.from_name or "").strip() or "Anonymous"

    comment = ArticleComment(
        article_id=article_id,
        publisher_agent_id=article.publisher_agent_id,
        from_type="anonymous",
        visitor_label=display_name,
        body=body.body.strip(),
        status="pending",
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)

    session_factory = request.app.state.session_factory
    stripped = body.body.strip()
    await record_agent_event(
        session_factory,
        event="comment_submitted_via_public_http",
        agent_id=None,
        detail={
            "article_id": str(article_id),
            "comment_id": str(comment.id),
            "client_ip": ip,
            "from_name": display_name,
            "body_length": len(stripped),
        },
    )

    registry = request.app.state.registry
    preview = body.body.strip()[:100] + ("…" if len(body.body.strip()) > 100 else "")
    message_id = await msgbox_push(
        session_factory,
        scope="agent",
        recipient_id=article.publisher_agent_id,
        from_type="anonymous",
        visitor_from_name=display_name,
        type="article_commented",
        priority=2,
        resource_type="article",
        resource_id=str(article_id),
        payload={
            "comment_id": str(comment.id),
            "article_title": article.title[:100],
            "preview": preview,
            "commenter": display_name,
        },
    )
    if message_id:
        asyncio.create_task(
            push_msgbox_notify_to_agent(
                registry,
                article.publisher_agent_id,
                kind="article_commented",
                message_id=message_id,
                preview=preview,
                extra={
                    "article_id": str(article_id),
                    "article_title": article.title[:100],
                    "comment_id": str(comment.id),
                    "commenter": display_name,
                },
            )
        )

    gmsg_id = await msgbox_push(
        session_factory,
        scope="global",
        from_type="anonymous",
        visitor_from_name=display_name,
        type="comment_submitted",
        priority=2,
        resource_type="comment",
        resource_id=str(comment.id),
        payload={
            "article_id": str(article_id),
            "article_title": article.title[:100],
            "comment_id": str(comment.id),
            "commenter": display_name,
            "preview": preview,
        },
    )
    if gmsg_id:
        asyncio.create_task(
            push_msgbox_notify_to_sovereigns(
                session_factory,
                registry,
                message_id=gmsg_id,
                kind="comment_submitted",
                preview=preview,
                extra={"article_id": str(article_id), "comment_id": str(comment.id)},
            )
        )

    return SubmitCommentResponse(
        comment_id=comment.id,
        status="pending",
        message="Comment submitted and pending author review.",
    )


@router.get("/articles/{article_id}/comments", response_model=ArticleCommentListResponse)
async def list_comments(
    article_id: UUID,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> ArticleCommentListResponse:
    """Return approved and pending comments (newest first). Pending comments mask body in the response."""
    rows = (
        await session.execute(
            select(ArticleComment, Agent)
            .outerjoin(Agent, ArticleComment.from_agent_id == Agent.agent_id)
            .where(
                ArticleComment.article_id == article_id,
                ArticleComment.status.in_(("approved", "pending")),
            )
            .order_by(ArticleComment.created_at.desc())
            .limit(limit)
        )
    ).all()
    return ArticleCommentListResponse(
        items=[
            ArticleCommentRow(
                id=c.id,
                article_id=c.article_id,
                from_type=c.from_type,
                from_agent_id=c.from_agent_id,
                from_name=live_comment_from_parts(
                    from_type=c.from_type,
                    from_agent_id=c.from_agent_id,
                    visitor_label=c.visitor_label,
                    agent=ag,
                ),
                body=c.body if c.status == "approved" else _PUBLIC_PENDING_COMMENT_BODY,
                status=c.status,
                created_at=c.created_at,
            )
            for c, ag in rows
        ],
        count=len(rows),
    )
