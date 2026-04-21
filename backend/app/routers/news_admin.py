from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.deps import DbSession, SettingsDep, admin_key_guard
from app.models import Agent, NewsArticle
from app.schemas import (
    NewsArticleAdminCreateRequest,
    NewsArticleAdminDetailResponse,
    NewsArticleAdminPatchRequest,
    NewsArticleAdminUpdateRequest,
    NewsArticleListResponse,
    NewsArticleListRow,
)
from app.services.markdown_storage import resolve_markdown_path

router = APIRouter(
    prefix="/v2/admin/news",
    tags=["admin-news"],
    dependencies=[Depends(admin_key_guard)],
)


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


async def _get_agent_or_404(session: DbSession, agent_id: str) -> Agent:
    agent = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publisher agent not found.",
        )
    return agent


@router.post("/articles", response_model=NewsArticleAdminDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_news_article(
    body: NewsArticleAdminCreateRequest, session: DbSession, settings: SettingsDep
) -> NewsArticleAdminDetailResponse:
    markdown_file = _resolve_markdown_file_or_400(body.markdown_path, settings.news_markdown_root)
    publisher = await _get_agent_or_404(session, body.publisher_agent_id.strip())

    article = NewsArticle(
        title=body.title.strip(),
        summary=body.summary.strip(),
        cover_image_url=body.cover_image_url.strip(),
        markdown_path=body.markdown_path.strip(),
        publisher_agent_id=publisher.agent_id,
        publisher_agent_name=publisher.agent_name,
        tags=[tag.strip() for tag in body.tags if tag.strip()],
        keywords=[k.strip() for k in body.keywords if k.strip()],
        published_at=body.published_at,
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
        publisher_agent_name=article.publisher_agent_name,
        tags=article.tags,
        keywords=article.keywords,
        published_at=article.published_at,
        markdown_content=markdown_content,
    )


@router.get("/articles", response_model=NewsArticleListResponse)
async def list_news_articles_admin(session: DbSession) -> NewsArticleListResponse:
    result = await session.scalars(
        select(NewsArticle).order_by(NewsArticle.published_at.desc(), NewsArticle.created_at.desc())
    )
    rows = result.all()
    return NewsArticleListResponse(
        items=[
            NewsArticleListRow(
                id=row.id,
                title=row.title,
                summary=row.summary,
                cover_image_url=row.cover_image_url,
                publisher_agent_id=row.publisher_agent_id,
                publisher_agent_name=row.publisher_agent_name,
                tags=row.tags,
                keywords=row.keywords,
                published_at=row.published_at,
            )
            for row in rows
        ]
    )


@router.get("/articles/{article_id}", response_model=NewsArticleAdminDetailResponse)
async def get_news_article_admin(
    article_id: UUID, session: DbSession, settings: SettingsDep
) -> NewsArticleAdminDetailResponse:
    article = await _get_article_or_404(session, article_id)
    markdown_file = _resolve_markdown_file_or_400(article.markdown_path, settings.news_markdown_root)
    markdown_content = markdown_file.read_text(encoding="utf-8")
    return NewsArticleAdminDetailResponse(
        id=article.id,
        title=article.title,
        summary=article.summary,
        cover_image_url=article.cover_image_url,
        markdown_path=article.markdown_path,
        publisher_agent_id=article.publisher_agent_id,
        publisher_agent_name=article.publisher_agent_name,
        tags=article.tags,
        keywords=article.keywords,
        published_at=article.published_at,
        markdown_content=markdown_content,
    )


@router.put("/articles/{article_id}", response_model=NewsArticleAdminDetailResponse)
async def update_news_article(
    article_id: UUID, body: NewsArticleAdminUpdateRequest, session: DbSession, settings: SettingsDep
) -> NewsArticleAdminDetailResponse:
    article = await _get_article_or_404(session, article_id)
    markdown_file = _resolve_markdown_file_or_400(body.markdown_path, settings.news_markdown_root)
    publisher = await _get_agent_or_404(session, body.publisher_agent_id.strip())

    article.title = body.title.strip()
    article.summary = body.summary.strip()
    article.cover_image_url = body.cover_image_url.strip()
    article.markdown_path = body.markdown_path.strip()
    article.publisher_agent_id = publisher.agent_id
    article.publisher_agent_name = publisher.agent_name
    article.tags = [tag.strip() for tag in body.tags if tag.strip()]
    article.keywords = [k.strip() for k in body.keywords if k.strip()]
    article.published_at = body.published_at
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
        publisher_agent_name=article.publisher_agent_name,
        tags=article.tags,
        keywords=article.keywords,
        published_at=article.published_at,
        markdown_content=markdown_content,
    )


@router.patch("/articles/{article_id}", response_model=NewsArticleAdminDetailResponse)
async def patch_news_article(
    article_id: UUID, body: NewsArticleAdminPatchRequest, session: DbSession, settings: SettingsDep
) -> NewsArticleAdminDetailResponse:
    article = await _get_article_or_404(session, article_id)

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

    await session.commit()
    await session.refresh(article)

    markdown_file = _resolve_markdown_file_or_400(article.markdown_path, settings.news_markdown_root)
    markdown_content = markdown_file.read_text(encoding="utf-8")
    return NewsArticleAdminDetailResponse(
        id=article.id,
        title=article.title,
        summary=article.summary,
        cover_image_url=article.cover_image_url,
        markdown_path=article.markdown_path,
        publisher_agent_id=article.publisher_agent_id,
        publisher_agent_name=article.publisher_agent_name,
        tags=article.tags,
        keywords=article.keywords,
        published_at=article.published_at,
        markdown_content=markdown_content,
    )


@router.delete("/articles/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_news_article(article_id: UUID, session: DbSession) -> None:
    article = await _get_article_or_404(session, article_id)
    await session.delete(article)
    await session.commit()
