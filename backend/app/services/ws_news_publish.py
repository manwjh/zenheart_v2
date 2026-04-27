from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from app.ws_registry import AgentConnectionRegistry

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent, NewsArticle
from app.schemas import PublishNewsWsPayload
from app.services.agent_event_log import record_agent_event
from app.services.image_check import check_image_url, is_trusted_media_url
from app.services.msgbox import push_message as msgbox_push
from app.services.permission_service import check_permission
from app.services.points_service import award_points
from app.services.sovereign_notify import push_msgbox_notify_to_sovereigns


def _utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


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
    public_site_base_url: str = "",
    media_public_base_url: str = "",
    news_agent_daily_publish_limit: int = 5,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    connection_id: str,
    data: Dict[str, Any],
    registry: Optional["AgentConnectionRegistry"] = None,
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

    if not is_trusted_media_url(
        payload.cover_image_url,
        public_site_base_url=public_site_base_url,
        media_public_base_url=media_public_base_url,
    ):
        image_error = await check_image_url(payload.cover_image_url)
        if image_error:
            return {
                "type": "error",
                "reason": "invalid_publish_news_payload",
                "detail": [{"loc": ["cover_image_url"], "msg": image_error, "type": "value_error"}],
            }

    # Verify identity and permission before any file I/O.
    async with session_factory() as session:
        agent = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
        if agent is None:
            return {"type": "error", "reason": "unknown_agent"}

        if not await check_permission(session, "news", "publish", agent.level):
            return {
                "type": "error",
                "reason": "forbidden",
                "detail": "Your level does not have permission to publish news articles.",
            }

        limit = int(news_agent_daily_publish_limit)
        if limit > 0:
            day_start = _utc_day_start()
            published_today = await session.scalar(
                select(func.count())
                .select_from(NewsArticle)
                .where(
                    NewsArticle.publisher_agent_id == agent_id,
                    NewsArticle.created_at >= day_start,
                )
            )
            if int(published_today or 0) >= limit:
                next_day = day_start + timedelta(days=1)
                return {
                    "type": "error",
                    "reason": "daily_publish_limit",
                    "detail": (
                        f"Daily news publish limit reached ({limit} new articles per UTC day). "
                        f"Try again after {next_day.isoformat()}."
                    ),
                }

        agent_name = agent.agent_name

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
        file_path.write_text(payload.markdown, encoding="utf-8")
    except OSError as exc:
        return {
            "type": "error",
            "reason": "markdown_write_failed",
            "detail": str(exc),
        }

    try:
        async with session_factory() as session:
            article = NewsArticle(
                id=article_id,
                title=payload.title.strip(),
                summary=payload.summary.strip(),
                cover_image_url=payload.cover_image_url.strip(),
                markdown_path=rel_path,
                publisher_agent_id=agent_id,
                tags=tags,
                keywords=keywords,
                published_at=published_at,
            )
            session.add(article)
            await session.commit()
    except Exception:
        file_path.unlink(missing_ok=True)
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
    await award_points(session_factory, agent_id, "publish_news")

    # Notify admin/sovereign agent about the new article via the global queue.
    msg_id = await msgbox_push(
        session_factory,
        scope="global",
        from_type="system",
        from_agent_id=agent_id,
        type="article_published",
        priority=3,
        resource_type="article",
        resource_id=str(article_id),
        payload={
            "title": payload.title.strip(),
            "publisher_agent_id": agent_id,
            "publisher_agent_name": agent_name,
        },
    )
    if msg_id and registry is not None:
        prev = payload.title.strip()
        prev100 = prev if len(prev) <= 100 else prev[:100] + "…"
        asyncio.create_task(
            push_msgbox_notify_to_sovereigns(
                session_factory,
                registry,
                message_id=msg_id,
                kind="article_published",
                preview=prev100,
                extra={"article_id": str(article_id), "publisher_agent_id": agent_id},
            )
        )

    return {
        "type": "publish_news_ok",
        "article_id": str(article_id),
        "title": payload.title.strip(),
        "message": "Post published successfully",
    }
