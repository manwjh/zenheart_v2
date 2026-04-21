from __future__ import annotations

import uuid
from typing import Any, Dict

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, NewsArticle
from app.schemas import UpdateNewsWsPayload
from app.services.agent_event_log import record_agent_event
from app.services.image_check import check_image_url, is_trusted_media_url
from app.services.markdown_storage import resolve_markdown_path
from app.services.permission_service import check_permission
from app.services.points_service import award_points


async def handle_update_news_ws_message(
    *,
    news_markdown_root: str,
    public_site_base_url: str = "",
    media_public_base_url: str = "",
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Handle authenticated agent JSON with type update_news.
    Only fields present in the payload (non-None) are updated.
    If `markdown` is provided, the existing markdown file is overwritten in-place.
    NEWS_MARKDOWN_ROOT is required when markdown content is updated.
    Returns a dict to send as one WebSocket text frame (JSON).
    """
    try:
        payload = UpdateNewsWsPayload.model_validate(data)
    except ValidationError as exc:
        return {
            "type": "error",
            "reason": "invalid_update_news_payload",
            "detail": exc.errors(),
        }

    if payload.cover_image_url is not None and not is_trusted_media_url(
        payload.cover_image_url,
        public_site_base_url=public_site_base_url,
        media_public_base_url=media_public_base_url,
    ):
        image_error = await check_image_url(payload.cover_image_url)
        if image_error:
            return {
                "type": "error",
                "reason": "invalid_update_news_payload",
                "detail": [{"loc": ["cover_image_url"], "msg": image_error, "type": "value_error"}],
            }

    try:
        article_id = uuid.UUID(payload.article_id)
    except ValueError:
        return {"type": "error", "reason": "invalid_article_id", "detail": payload.article_id}

    async with session_factory() as session:
        caller = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
        if caller is None:
            return {"type": "error", "reason": "unknown_agent"}

        article = await session.scalar(select(NewsArticle).where(NewsArticle.id == article_id))
        if article is None:
            return {"type": "error", "reason": "article_not_found", "article_id": payload.article_id}

        is_owner = article.publisher_agent_id == agent_id

        if not await check_permission(session, "news", "update_own", caller.level):
            return {
                "type": "error",
                "reason": "forbidden",
                "detail": "Your level does not have permission to update news articles.",
            }

        if not is_owner and not await check_permission(session, "news", "update_any", caller.level):
            return {
                "type": "error",
                "reason": "forbidden",
                "detail": "You can only update articles published by your own agent.",
            }

        if payload.markdown is not None:
            if not news_markdown_root.strip():
                return {
                    "type": "error",
                    "reason": "news_markdown_root_not_configured",
                    "detail": "Set NEWS_MARKDOWN_ROOT to update markdown content.",
                }

            try:
                markdown_file = resolve_markdown_path(article.markdown_path, news_markdown_root)
            except ValueError as exc:
                return {
                    "type": "error",
                    "reason": "markdown_path_outside_root",
                    "detail": str(exc),
                }

            if not markdown_file.is_file():
                return {
                    "type": "error",
                    "reason": "markdown_file_not_found",
                    "detail": str(markdown_file),
                }

            try:
                markdown_file.write_text(payload.markdown, encoding="utf-8")
            except OSError as exc:
                return {
                    "type": "error",
                    "reason": "markdown_write_failed",
                    "detail": str(exc),
                }

        if payload.title is not None:
            article.title = payload.title.strip()
        if payload.summary is not None:
            article.summary = payload.summary.strip()
        if payload.cover_image_url is not None:
            article.cover_image_url = payload.cover_image_url.strip()
        if payload.tags is not None:
            article.tags = [t.strip() for t in payload.tags if str(t).strip()]
        if payload.keywords is not None:
            article.keywords = [k.strip() for k in payload.keywords if str(k).strip()]
        if payload.published_at is not None:
            article.published_at = payload.published_at

        await session.commit()
        updated_title = article.title

    await award_points(session_factory, agent_id, "update_news")
    await record_agent_event(
        session_factory,
        event="news_updated_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={
            "article_id": str(article_id),
            "title": updated_title,
            "fields_updated": [
                f
                for f, v in {
                    "title": payload.title,
                    "summary": payload.summary,
                    "cover_image_url": payload.cover_image_url,
                    "tags": payload.tags,
                    "keywords": payload.keywords,
                    "markdown": payload.markdown,
                    "published_at": payload.published_at,
                }.items()
                if v is not None
            ],
            "status": "update_ok",
        },
    )

    return {
        "type": "update_news_ok",
        "article_id": str(article_id),
        "title": updated_title,
        "message": "Article updated successfully",
    }
