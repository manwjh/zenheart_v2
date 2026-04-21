from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import DbSession, SettingsDep
from app.models import NewsArticle
from app.schemas import (
    NewsArticleDetailResponse,
    NewsArticleListResponse,
    NewsArticleListRow,
)
from app.services.markdown_storage import resolve_markdown_path

router = APIRouter(prefix="/v2/news", tags=["news"])


@router.get("/articles", response_model=NewsArticleListResponse)
async def list_news_articles(session: DbSession) -> NewsArticleListResponse:
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
        markdown_content=markdown_content,
    )
