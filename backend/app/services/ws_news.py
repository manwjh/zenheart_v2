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

from app.model_defs import Agent, NewsArticle
from app.schemas import DeleteNewsWsPayload, PublishNewsWsPayload, UpdateNewsWsPayload
from app.services.agent_event_log import record_agent_event
from app.services.image_check import verify_news_cover_image_url
from app.services.markdown_storage import resolve_markdown_path
from app.services.msgbox import push_message as msgbox_push
from app.services.permission_service import check_permission
from app.services.points_service import award_points
from app.services.sovereign_notify import push_msgbox_notify_to_sovereigns

_UPDATE_WS_FIELDS = (
    "title",
    "summary",
    "cover_image_url",
    "tags",
    "keywords",
    "markdown",
    "published_at",
)


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


def _parse_article_id(raw: str) -> uuid.UUID | dict[str, Any]:
    try:
        return uuid.UUID(raw)
    except ValueError:
        return {"type": "error", "reason": "invalid_article_id", "detail": raw}


def _resolved_publish_markdown_root(news_markdown_root: str) -> Path | dict[str, Any]:
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
    return root


def _normalized_str_list(items: list[str]) -> list[str]:
    return [x.strip() for x in items if str(x).strip()]


def _preview_truncated(text: str, max_len: int = 100) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _update_fields_touched(payload: UpdateNewsWsPayload) -> list[str]:
    return [name for name in _UPDATE_WS_FIELDS if getattr(payload, name) is not None]


async def _reject_if_cover_image_invalid(
    cover_image_url: Optional[str],
    *,
    ws_error_reason: str,
    public_site_base_url: str,
    media_root: str,
) -> dict[str, Any] | None:
    if cover_image_url is None:
        return None
    image_error = await verify_news_cover_image_url(
        cover_image_url,
        public_site_base_url=public_site_base_url,
        media_root=media_root,
    )
    if image_error:
        return {
            "type": "error",
            "reason": ws_error_reason,
            "detail": [
                {"loc": ["cover_image_url"], "msg": image_error, "type": "value_error"}
            ],
        }
    return None


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

    parsed = _parse_article_id(payload.article_id)
    if isinstance(parsed, dict):
        return parsed
    article_id = parsed

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

    # Best-effort: delete markdown after the DB row is removed.
    # resolve_markdown_path accepts relative paths under NEWS_MARKDOWN_ROOT and legacy absolutes.
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


async def handle_publish_news_ws_message(
    *,
    news_markdown_root: str,
    public_site_base_url: str = "",
    media_root: str = "",
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
    root_or_err = _resolved_publish_markdown_root(news_markdown_root)
    if isinstance(root_or_err, dict):
        return root_or_err
    root = root_or_err

    try:
        payload = PublishNewsWsPayload.model_validate(data)
    except ValidationError as exc:
        return {
            "type": "error",
            "reason": "invalid_publish_news_payload",
            "detail": exc.errors(),
        }

    cover_err = await _reject_if_cover_image_invalid(
        payload.cover_image_url,
        ws_error_reason="invalid_publish_news_payload",
        public_site_base_url=public_site_base_url,
        media_root=media_root,
    )
    if cover_err is not None:
        return cover_err

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
    tags = _normalized_str_list(payload.tags)
    keywords = _normalized_str_list(payload.keywords)

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

    title_stripped = payload.title.strip()
    await record_agent_event(
        session_factory,
        event="news_published_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={
            "article_id": str(article_id),
            "title": title_stripped,
            "markdown_path": rel_path,
            "status": "post_published_ok",
        },
    )
    await award_points(session_factory, agent_id, "publish_news")

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
            "title": title_stripped,
            "publisher_agent_id": agent_id,
            "publisher_agent_name": agent_name,
        },
    )
    if msg_id and registry is not None:
        asyncio.create_task(
            push_msgbox_notify_to_sovereigns(
                session_factory,
                registry,
                message_id=msg_id,
                kind="article_published",
                preview=_preview_truncated(title_stripped),
                extra={"article_id": str(article_id), "publisher_agent_id": agent_id},
            )
        )

    return {
        "type": "publish_news_ok",
        "article_id": str(article_id),
        "title": title_stripped,
        "message": "Post published successfully",
    }


async def handle_update_news_ws_message(
    *,
    news_markdown_root: str,
    public_site_base_url: str = "",
    media_root: str = "",
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

    cover_err = await _reject_if_cover_image_invalid(
        payload.cover_image_url,
        ws_error_reason="invalid_update_news_payload",
        public_site_base_url=public_site_base_url,
        media_root=media_root,
    )
    if cover_err is not None:
        return cover_err

    parsed = _parse_article_id(payload.article_id)
    if isinstance(parsed, dict):
        return parsed
    article_id = parsed

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
            article.tags = _normalized_str_list(payload.tags)
        if payload.keywords is not None:
            article.keywords = _normalized_str_list(payload.keywords)
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
            "fields_updated": _update_fields_touched(payload),
            "status": "update_ok",
        },
    )

    return {
        "type": "update_news_ok",
        "article_id": str(article_id),
        "title": updated_title,
        "message": "Article updated successfully",
    }
