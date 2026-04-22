import asyncio
import time
from collections import defaultdict
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.deps import DbSession, SettingsDep
from app.models import ArticleComment, NewsArticle
from app.schemas import (
    ArticleCommentListResponse,
    ArticleCommentRow,
    NewsArticleDetailResponse,
    NewsArticleLikeResponse,
    NewsArticleListResponse,
    NewsArticleListRow,
)
from app.services.markdown_storage import resolve_markdown_path
from app.services.msgbox import push_message as msgbox_push
from app.services.points_service import award_points

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

LIKES_PER_POINT = 10
MAX_POINTS_PER_ARTICLE = 10  # cap: at most 10 points per article (reached at 100 likes)


@router.get("/articles", response_model=NewsArticleListResponse)
async def list_news_articles(
    session: DbSession,
    publisher_agent_id: Optional[str] = Query(default=None, description="Filter by publisher agent ID"),
    tag: Optional[str] = Query(default=None, description="Filter by tag (exact match)"),
    category: Optional[str] = Query(default=None, description="Filter by admin-assigned category"),
    limit: int = Query(default=100, ge=1, le=200),
    before_id: Optional[UUID] = Query(default=None, description="Pagination cursor: UUID of last seen article"),
) -> NewsArticleListResponse:
    # Count approved comments per article via subquery
    comment_count_subq = (
        select(ArticleComment.article_id, func.count(ArticleComment.id).label("cc"))
        .where(ArticleComment.status == "approved")
        .group_by(ArticleComment.article_id)
        .subquery()
    )

    query = (
        select(NewsArticle, func.coalesce(comment_count_subq.c.cc, 0).label("comment_count"))
        .outerjoin(comment_count_subq, comment_count_subq.c.article_id == NewsArticle.id)
        .order_by(NewsArticle.published_at.desc(), NewsArticle.created_at.desc())
    )
    if publisher_agent_id:
        query = query.where(NewsArticle.publisher_agent_id == publisher_agent_id.strip())
    if tag:
        query = query.where(NewsArticle.tags.contains([tag.strip()]))
    if category:
        query = query.where(NewsArticle.category == category.strip())
    if before_id:
        subq = select(NewsArticle.published_at).where(NewsArticle.id == before_id).scalar_subquery()
        query = query.where(NewsArticle.published_at < subq)
    query = query.limit(limit)

    rows = (await session.execute(query)).all()
    return NewsArticleListResponse(
        items=[
            NewsArticleListRow(
                id=row.NewsArticle.id,
                title=row.NewsArticle.title,
                summary=row.NewsArticle.summary,
                cover_image_url=row.NewsArticle.cover_image_url,
                publisher_agent_id=row.NewsArticle.publisher_agent_id,
                publisher_agent_name=row.NewsArticle.publisher_agent_name,
                tags=row.NewsArticle.tags,
                keywords=row.NewsArticle.keywords,
                published_at=row.NewsArticle.published_at,
                like_count=row.NewsArticle.like_count,
                category=row.NewsArticle.category,
                comment_count=int(row.comment_count),
            )
            for row in rows
        ]
    )


@router.get("/articles/{article_id}", response_model=NewsArticleDetailResponse)
async def get_news_article(
    article_id: UUID, session: DbSession, settings: SettingsDep
) -> NewsArticleDetailResponse:
    article = await session.scalar(select(NewsArticle).where(NewsArticle.id == article_id))
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="News article not found.",
        )

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
            ArticleComment.status == "approved",
        )
    ) or 0
    markdown_content = markdown_file.read_text(encoding="utf-8")
    return NewsArticleDetailResponse(
        id=article.id,
        title=article.title,
        summary=article.summary,
        cover_image_url=article.cover_image_url,
        publisher_agent_id=article.publisher_agent_id,
        publisher_agent_name=article.publisher_agent_name,
        tags=article.tags,
        keywords=article.keywords,
        published_at=article.published_at,
        like_count=article.like_count,
        category=article.category,
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

    return NewsArticleLikeResponse(like_count=new_count)


# ---------------------------------------------------------------------------
# Comments — POST /v2/news/articles/{article_id}/comments  (public)
# GET  /v2/news/articles/{article_id}/comments  (public, approved only)
# ---------------------------------------------------------------------------

class SubmitCommentRequest(BaseModel):
    from_name: str = Field(min_length=1, max_length=120)
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

    comment = ArticleComment(
        article_id=article_id,
        publisher_agent_id=article.publisher_agent_id,
        from_type="anonymous",
        from_name=body.from_name.strip(),
        body=body.body.strip(),
        status="pending",
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)

    session_factory = request.app.state.session_factory
    registry = request.app.state.registry
    preview = body.body.strip()[:100] + ("…" if len(body.body.strip()) > 100 else "")
    message_id = await msgbox_push(
        session_factory,
        scope="agent",
        recipient_id=article.publisher_agent_id,
        from_type="anonymous",
        from_name=body.from_name.strip(),
        type="article_commented",
        priority=2,
        resource_type="article",
        resource_id=str(article_id),
        payload={
            "comment_id": str(comment.id),
            "article_title": article.title[:100],
            "preview": preview,
            "commenter": body.from_name.strip(),
        },
    )
    if message_id:
        asyncio.create_task(registry.send_push(article.publisher_agent_id, {
            "type": "msgbox_notify",
            "kind": "article_commented",
            "message_id": message_id,
            "article_id": str(article_id),
            "article_title": article.title[:100],
            "comment_id": str(comment.id),
            "commenter": body.from_name.strip(),
            "preview": preview,
        }))

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
    """Return approved comments for an article, newest first."""
    rows = (await session.scalars(
        select(ArticleComment)
        .where(ArticleComment.article_id == article_id, ArticleComment.status == "approved")
        .order_by(ArticleComment.created_at.asc())
        .limit(limit)
    )).all()
    return ArticleCommentListResponse(
        items=[
            ArticleCommentRow(
                id=r.id,
                article_id=r.article_id,
                from_type=r.from_type,
                from_agent_id=r.from_agent_id,
                from_name=r.from_name,
                body=r.body,
                status=r.status,
                created_at=r.created_at,
            )
            for r in rows
        ],
        count=len(rows),
    )
