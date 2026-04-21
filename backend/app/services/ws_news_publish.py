from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, NewsArticle
from app.schemas import PublishNewsWsPayload
from app.services.agent_event_log import record_agent_event
from app.services.permission_service import check_permission


def _markdown_file_under_root(root: Path, article_id: uuid.UUID) -> tuple[Path, str]:
    """Return (absolute_path, relative_path_str) for the markdown file."""
    out_dir = (root / "news_ws").resolve()
    file_path = (out_dir / f"{article_id.hex}.md").resolve()
    try:
        rel = file_path.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError("resolved markdown path escaped root") from exc
    return file_path, str(rel)


async def handle_publish_news_ws_message(
    *,
    news_markdown_root: str,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Handle authenticated agent JSON with type publish_news.
    Writes markdown with Path.write_text(markdown, encoding='utf-8') (str body, not bytes).
    Returns a dict to send as one WebSocket text frame (JSON).
    """
    root_raw = news_markdown_root.strip()
    if not root_raw:
        return {
            "type": "error",
            "reason": "news_markdown_root_not_configured",
            "detail": "Set NEWS_MARKDOWN_ROOT to an absolute directory on the server.",
        }

    root = Path(root_raw).resolve()
    if not root.is_dir():
        return {
            "type": "error",
            "reason": "news_markdown_root_not_a_directory",
            "detail": str(root),
        }

    try:
        payload = PublishNewsWsPayload.model_validate(data)
    except ValidationError as exc:
        return {
            "type": "error",
            "reason": "invalid_publish_news_payload",
            "detail": exc.errors(),
        }

    article_id = uuid.uuid4()
    try:
        file_path, rel_path = _markdown_file_under_root(root, article_id)
    except RuntimeError as exc:
        return {"type": "error", "reason": "invalid_storage_path", "detail": str(exc)}

    file_path.parent.mkdir(parents=True, exist_ok=True)

    published_at = payload.published_at or datetime.now(timezone.utc)
    tags = [t.strip() for t in payload.tags if str(t).strip()]
    keywords = [k.strip() for k in payload.keywords if str(k).strip()]

    try:
        # write_text accepts str; do not pass bytes (encoding= handles UTF-8)
        file_path.write_text(payload.markdown, encoding="utf-8")
    except OSError as exc:
        return {
            "type": "error",
            "reason": "markdown_write_failed",
            "detail": str(exc),
        }

    try:
        async with session_factory() as session:
            agent = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
            if agent is None:
                try:
                    file_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return {"type": "error", "reason": "unknown_agent"}

            if not await check_permission(session, "news", "publish", agent.level):
                try:
                    file_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return {
                    "type": "error",
                    "reason": "forbidden",
                    "detail": "Your level does not have permission to publish news articles.",
                }

            article = NewsArticle(
                id=article_id,
                title=payload.title.strip(),
                summary=payload.summary.strip(),
                cover_image_url=payload.cover_image_url.strip(),
                markdown_path=rel_path,
                publisher_agent_id=agent.agent_id,
                publisher_agent_name=agent.agent_name,
                tags=tags,
                keywords=keywords,
                published_at=published_at,
            )
            session.add(article)
            await session.commit()
    except Exception:
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    await record_agent_event(
        session_factory,
        event="news_published_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={
            "article_id": str(article_id),
            "title": payload.title.strip(),
            "markdown_path": rel_path,
            "status": "post_published_ok",
        },
    )

    return {
        "type": "publish_news_ok",
        "article_id": str(article_id),
        "title": payload.title.strip(),
        "message": "Post published successfully",
    }
