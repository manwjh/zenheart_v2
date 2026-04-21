from __future__ import annotations

import uuid
from typing import Any, Dict

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, NewsArticle
from app.schemas import DeleteNewsWsPayload
from app.services.agent_event_log import record_agent_event
from app.services.markdown_storage import resolve_markdown_path
from app.services.permission_service import check_permission


async def handle_delete_news_ws_message(
    *,
    news_markdown_root: str,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Handle authenticated agent JSON with type delete_news.
    Deletes the markdown file (best-effort) and removes the DB row.
    Returns a dict to send as one WebSocket text frame (JSON).
    """
    try:
        payload = DeleteNewsWsPayload.model_validate(data)
    except ValidationError as exc:
        return {
            "type": "error",
            "reason": "invalid_delete_news_payload",
            "detail": exc.errors(),
        }

    try:
        article_id = uuid.UUID(payload.article_id)
    except ValueError:
        return {
            "type": "error",
            "reason": "invalid_article_id",
            "detail": payload.article_id,
        }

    async with session_factory() as session:
        caller = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
        if caller is None:
            return {"type": "error", "reason": "unknown_agent"}

        article = await session.scalar(
            select(NewsArticle).where(NewsArticle.id == article_id)
        )
        if article is None:
            return {
                "type": "error",
                "reason": "article_not_found",
                "article_id": payload.article_id,
            }

        is_owner = article.publisher_agent_id == agent_id

        if not await check_permission(session, "news", "delete_own", caller.level):
            return {
                "type": "error",
                "reason": "forbidden",
                "detail": "Your level does not have permission to delete news articles.",
            }

        if not is_owner and not await check_permission(
            session, "news", "delete_any", caller.level
        ):
            return {
                "type": "error",
                "reason": "forbidden",
                "detail": "You can only delete articles published by your own agent.",
            }

        markdown_path = article.markdown_path
        deleted_title = article.title

        await session.delete(article)
        await session.commit()

    # Best-effort: remove markdown file after DB row is gone.
    # resolve_markdown_path handles both relative (relative to NEWS_MARKDOWN_ROOT)
    # and legacy absolute paths, and guards against path traversal.
    try:
        if news_markdown_root.strip() or markdown_path.startswith("/"):
            p = resolve_markdown_path(markdown_path, news_markdown_root)
            if p.is_file():
                p.unlink()
    except (OSError, ValueError):
        pass

    await record_agent_event(
        session_factory,
        event="news_deleted_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={
            "article_id": str(article_id),
            "title": deleted_title,
            "status": "delete_ok",
        },
    )

    return {
        "type": "delete_news_ok",
        "article_id": str(article_id),
        "title": deleted_title,
        "message": "Article deleted successfully",
    }
