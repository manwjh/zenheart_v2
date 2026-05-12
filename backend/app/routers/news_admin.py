from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.config import Settings
from app.deps import DbSession, SettingsDep, admin_or_sovereign_guard
from app.model_defs import Agent, NewsArticle, NewsColumnMember
from app.schemas import (
    NewsArticleCategory,
    NewsArticleAdminCreateRequest,
    NewsArticleAdminDetailResponse,
    NewsArticleAdminPatchRequest,
    NewsArticleAdminUpdateRequest,
    NewsArticleListResponse,
    NewsArticleListRow,
    NewsColumnAdminAddRequest,
    NewsColumnAdminListResponse,
    NewsColumnAdminOrderRequest,
    NewsColumnAdminRow,
)
from app.services.display_name_resolve import live_display_name_from_snapshot
from app.services.image_check import verify_news_cover_image_url
from app.services.markdown_storage import resolve_markdown_path

router = APIRouter(
    prefix="/v2/admin/news",
    tags=["admin-news"],
    dependencies=[Depends(admin_or_sovereign_guard)],
)


def _to_category(level1: str | None, level2: str | None) -> NewsArticleCategory | None:
    if not level1 and not level2:
        return None
    return NewsArticleCategory(primary=level1, secondary=level2)


def _resolve_markdown_file_or_400(markdown_path: str, news_markdown_root: str) -> Path:
    """Resolve and validate the markdown path; raise 400 if missing or invalid."""
    try:
        resolved = resolve_markdown_path(markdown_path, news_markdown_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resolve markdown path: {exc}",
        )
    if not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="markdown_path does not point to an existing file.",
        )
    return resolved


async def _get_article_or_404(session: DbSession, article_id: UUID) -> NewsArticle:
    article = await session.scalar(select(NewsArticle).where(NewsArticle.id == article_id))
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="News article not found.",
        )
    return article


async def _verify_cover_or_400(cover_image_url: str, settings: Settings) -> None:
    err = await verify_news_cover_image_url(
        cover_image_url.strip(),
        public_site_base_url=settings.public_site_base_url,
        media_root=settings.media_root,
    )
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)


async def _get_agent_or_404(session: DbSession, agent_id: str) -> Agent:
    agent = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publisher agent not found.",
        )
    return agent


async def _list_column_members_ordered(session: DbSession) -> list[NewsColumnMember]:
    return list(
        (
            await session.scalars(
                select(NewsColumnMember).order_by(
                    NewsColumnMember.sort_order.asc(), NewsColumnMember.agent_id.asc()
                )
            )
        ).all()
    )


def _admin_column_rows(
    members: list[NewsColumnMember], agents_by_id: dict[str, Agent]
) -> list[NewsColumnAdminRow]:
    return [
        NewsColumnAdminRow(
            agent_id=m.agent_id,
            sort_order=m.sort_order,
            display_name=live_display_name_from_snapshot(
                "", agents_by_id.get(m.agent_id), fallback_id=m.agent_id
            ),
        )
        for m in members
    ]


@router.get("/columns", response_model=NewsColumnAdminListResponse)
async def admin_list_news_columns(session: DbSession) -> NewsColumnAdminListResponse:
    members = await _list_column_members_ordered(session)
    if not members:
        return NewsColumnAdminListResponse(items=[])
    ids = [m.agent_id for m in members]
    agents = (await session.scalars(select(Agent).where(Agent.agent_id.in_(ids)))).all()
    by_id = {a.agent_id: a for a in agents}
    return NewsColumnAdminListResponse(items=_admin_column_rows(members, by_id))


@router.put("/columns/order", response_model=NewsColumnAdminListResponse)
async def admin_order_news_columns(
    body: NewsColumnAdminOrderRequest, session: DbSession
) -> NewsColumnAdminListResponse:
    ordered = [x.strip() for x in body.agent_ids]
    if not ordered or not all(ordered):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent_ids must be non-empty strings.",
        )
    if len(set(ordered)) != len(ordered):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate agent_id in agent_ids.",
        )
    for a in ordered:
        if len(a) > 80:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="agent_id too long.",
            )
    members = await _list_column_members_ordered(session)
    current_ids = [m.agent_id for m in members]
    if set(ordered) != set(current_ids) or len(ordered) != len(current_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent_ids must list every column member exactly once.",
        )
    member_by_id = {m.agent_id: m for m in members}
    for idx, aid in enumerate(ordered):
        member_by_id[aid].sort_order = idx
    await session.commit()
    members2 = await _list_column_members_ordered(session)
    ids2 = [m.agent_id for m in members2]
    agents = (await session.scalars(select(Agent).where(Agent.agent_id.in_(ids2)))).all()
    by_id = {a.agent_id: a for a in agents}
    return NewsColumnAdminListResponse(items=_admin_column_rows(members2, by_id))


@router.post("/columns", response_model=NewsColumnAdminRow, status_code=status.HTTP_201_CREATED)
async def admin_add_news_column(body: NewsColumnAdminAddRequest, session: DbSession) -> NewsColumnAdminRow:
    aid = body.agent_id.strip()
    await _get_agent_or_404(session, aid)
    existing = await session.scalar(select(NewsColumnMember).where(NewsColumnMember.agent_id == aid))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent already in news columns.",
        )
    max_ord = await session.scalar(select(func.max(NewsColumnMember.sort_order)))
    nxt = (max_ord + 1) if max_ord is not None else 0
    row = NewsColumnMember(agent_id=aid, sort_order=nxt)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    agent = await session.scalar(select(Agent).where(Agent.agent_id == aid))
    return NewsColumnAdminRow(
        agent_id=row.agent_id,
        sort_order=row.sort_order,
        display_name=live_display_name_from_snapshot("", agent, fallback_id=aid),
    )


@router.delete("/columns/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_news_column(agent_id: str, session: DbSession) -> None:
    aid = agent_id.strip()
    row = await session.scalar(select(NewsColumnMember).where(NewsColumnMember.agent_id == aid))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Column entry not found.",
        )
    await session.delete(row)
    await session.commit()


@router.post("/articles", response_model=NewsArticleAdminDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_news_article(
    body: NewsArticleAdminCreateRequest, session: DbSession, settings: SettingsDep
) -> NewsArticleAdminDetailResponse:
    markdown_file = _resolve_markdown_file_or_400(body.markdown_path, settings.news_markdown_root)
    publisher = await _get_agent_or_404(session, body.publisher_agent_id.strip())
    await _verify_cover_or_400(body.cover_image_url, settings)

    article = NewsArticle(
        title=body.title.strip(),
        summary=body.summary.strip(),
        cover_image_url=body.cover_image_url.strip(),
        markdown_path=body.markdown_path.strip(),
        publisher_agent_id=publisher.agent_id,
        tags=[tag.strip() for tag in body.tags if tag.strip()],
        keywords=[k.strip() for k in body.keywords if k.strip()],
        published_at=body.published_at,
        score=body.score,
        category_level1=body.category.primary.strip() if body.category and body.category.primary else None,
        category_level2=body.category.secondary.strip() if body.category and body.category.secondary else None,
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)

    markdown_content = markdown_file.read_text(encoding="utf-8")
    return NewsArticleAdminDetailResponse(
        id=article.id,
        title=article.title,
        summary=article.summary,
        cover_image_url=article.cover_image_url,
        markdown_path=article.markdown_path,
        publisher_agent_id=article.publisher_agent_id,
        publisher_agent_name=publisher.agent_name,
        tags=article.tags,
        keywords=article.keywords,
        published_at=article.published_at,
        like_count=article.like_count,
        read_count=article.read_count,
        score=article.score,
        category=_to_category(article.category_level1, article.category_level2),
        markdown_content=markdown_content,
    )


@router.get("/articles", response_model=NewsArticleListResponse)
async def list_news_articles_admin(session: DbSession) -> NewsArticleListResponse:
    result = await session.execute(
        select(NewsArticle, Agent)
        .outerjoin(Agent, NewsArticle.publisher_agent_id == Agent.agent_id)
        .order_by(NewsArticle.published_at.desc(), NewsArticle.created_at.desc())
    )
    rows = result.all()
    return NewsArticleListResponse(
        items=[
            NewsArticleListRow(
                id=art.id,
                title=art.title,
                summary=art.summary,
                cover_image_url=art.cover_image_url,
                publisher_agent_id=art.publisher_agent_id,
                publisher_agent_name=ag.agent_name
                if ag
                else (art.publisher_agent_id[:8] + "…")
                if len(art.publisher_agent_id) > 8
                else art.publisher_agent_id,
                tags=art.tags,
                keywords=art.keywords,
                published_at=art.published_at,
                like_count=art.like_count,
                read_count=art.read_count,
                score=art.score,
                category=_to_category(art.category_level1, art.category_level2),
            )
            for art, ag in rows
        ]
    )


@router.get("/articles/{article_id}", response_model=NewsArticleAdminDetailResponse)
async def get_news_article_admin(
    article_id: UUID, session: DbSession, settings: SettingsDep
) -> NewsArticleAdminDetailResponse:
    article = await _get_article_or_404(session, article_id)
    pub = await session.scalar(
        select(Agent).where(Agent.agent_id == article.publisher_agent_id)
    )
    pub_name = (
        pub.agent_name
        if pub
        else (
            (article.publisher_agent_id[:8] + "…")
            if len(article.publisher_agent_id) > 8
            else article.publisher_agent_id
        )
    )
    markdown_file = _resolve_markdown_file_or_400(article.markdown_path, settings.news_markdown_root)
    markdown_content = markdown_file.read_text(encoding="utf-8")
    return NewsArticleAdminDetailResponse(
        id=article.id,
        title=article.title,
        summary=article.summary,
        cover_image_url=article.cover_image_url,
        markdown_path=article.markdown_path,
        publisher_agent_id=article.publisher_agent_id,
        publisher_agent_name=pub_name,
        tags=article.tags,
        keywords=article.keywords,
        published_at=article.published_at,
        like_count=article.like_count,
        read_count=article.read_count,
        score=article.score,
        category=_to_category(article.category_level1, article.category_level2),
        markdown_content=markdown_content,
    )


@router.put("/articles/{article_id}", response_model=NewsArticleAdminDetailResponse)
async def update_news_article(
    article_id: UUID, body: NewsArticleAdminUpdateRequest, session: DbSession, settings: SettingsDep
) -> NewsArticleAdminDetailResponse:
    article = await _get_article_or_404(session, article_id)
    markdown_file = _resolve_markdown_file_or_400(body.markdown_path, settings.news_markdown_root)
    publisher = await _get_agent_or_404(session, body.publisher_agent_id.strip())
    await _verify_cover_or_400(body.cover_image_url, settings)

    article.title = body.title.strip()
    article.summary = body.summary.strip()
    article.cover_image_url = body.cover_image_url.strip()
    article.markdown_path = body.markdown_path.strip()
    article.publisher_agent_id = publisher.agent_id
    article.tags = [tag.strip() for tag in body.tags if tag.strip()]
    article.keywords = [k.strip() for k in body.keywords if k.strip()]
    article.published_at = body.published_at
    article.score = body.score
    article.category_level1 = body.category.primary.strip() if body.category and body.category.primary else None
    article.category_level2 = body.category.secondary.strip() if body.category and body.category.secondary else None
    await session.commit()
    await session.refresh(article)

    markdown_content = markdown_file.read_text(encoding="utf-8")
    return NewsArticleAdminDetailResponse(
        id=article.id,
        title=article.title,
        summary=article.summary,
        cover_image_url=article.cover_image_url,
        markdown_path=article.markdown_path,
        publisher_agent_id=article.publisher_agent_id,
        publisher_agent_name=publisher.agent_name,
        tags=article.tags,
        keywords=article.keywords,
        published_at=article.published_at,
        like_count=article.like_count,
        read_count=article.read_count,
        score=article.score,
        category=_to_category(article.category_level1, article.category_level2),
        markdown_content=markdown_content,
    )


@router.patch("/articles/{article_id}", response_model=NewsArticleAdminDetailResponse)
async def patch_news_article(
    article_id: UUID, body: NewsArticleAdminPatchRequest, session: DbSession, settings: SettingsDep
) -> NewsArticleAdminDetailResponse:
    article = await _get_article_or_404(session, article_id)

    if body.cover_image_url is not None:
        await _verify_cover_or_400(body.cover_image_url, settings)

    if body.title is not None:
        article.title = body.title.strip()
    if body.summary is not None:
        article.summary = body.summary.strip()
    if body.cover_image_url is not None:
        article.cover_image_url = body.cover_image_url.strip()
    if body.markdown_path is not None:
        _resolve_markdown_file_or_400(body.markdown_path, settings.news_markdown_root)
        article.markdown_path = body.markdown_path.strip()
    if body.tags is not None:
        article.tags = [tag.strip() for tag in body.tags if tag.strip()]
    if body.keywords is not None:
        article.keywords = [k.strip() for k in body.keywords if k.strip()]
    if body.published_at is not None:
        article.published_at = body.published_at
    if body.score is not None:
        article.score = body.score
    if body.category is not None:
        article.category_level1 = body.category.primary.strip() if body.category.primary else None
        article.category_level2 = body.category.secondary.strip() if body.category.secondary else None

    await session.commit()
    await session.refresh(article)

    pub = await session.scalar(
        select(Agent).where(Agent.agent_id == article.publisher_agent_id)
    )
    pub_name = (
        pub.agent_name
        if pub
        else (
            (article.publisher_agent_id[:8] + "…")
            if len(article.publisher_agent_id) > 8
            else article.publisher_agent_id
        )
    )
    markdown_file = _resolve_markdown_file_or_400(article.markdown_path, settings.news_markdown_root)
    markdown_content = markdown_file.read_text(encoding="utf-8")
    return NewsArticleAdminDetailResponse(
        id=article.id,
        title=article.title,
        summary=article.summary,
        cover_image_url=article.cover_image_url,
        markdown_path=article.markdown_path,
        publisher_agent_id=article.publisher_agent_id,
        publisher_agent_name=pub_name,
        tags=article.tags,
        keywords=article.keywords,
        published_at=article.published_at,
        like_count=article.like_count,
        read_count=article.read_count,
        score=article.score,
        category=_to_category(article.category_level1, article.category_level2),
        markdown_content=markdown_content,
    )


@router.delete("/articles/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_news_article(article_id: UUID, session: DbSession) -> None:
    article = await _get_article_or_404(session, article_id)
    await session.delete(article)
    await session.commit()
