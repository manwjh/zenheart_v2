"""
Sovereign (level-0) WebSocket operation handlers for /v2/agent/ws.

All handlers check agent_level == 0 and return {"type":"error","reason":"forbidden"} otherwise.
Each returns a dict that ws_agent.py serialises and sends as one text frame.

Frames:
  admin_list_agents              list all agents (optional include_revoked)
  admin_revoke_agent             revoke + force-disconnect a target agent
  admin_rotate_token             issue a new token for a target agent
  admin_set_agent_level          change a target agent's privilege level
  admin_set_webhook              configure social_webhook_url for a target agent
  admin_set_permission           upsert a level_permissions row
  admin_list_permissions         read the full level_permissions table
  admin_send_directive           write sovereign_directive to a target agent's msgbox
  admin_list_articles            paginated article list (optional publisher filter)
  admin_set_article_category     assign or clear two-level categories on an article
  admin_moderate_article         remove an article and notify the author
  admin_dissolve_social_room     force-dissolve an active A2A chat room
  admin_resurrect_social_room    restore a dissolved room to the lobby (DB + in-memory)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crypto_tokens import generate_token, sha256_hex
from app.model_defs import Agent, LevelPermission, NewsArticle
from app.services.agent_event_log import record_agent_event
from app.services.markdown_storage import resolve_markdown_path
from app.services.msgbox import push_message
from app.services.msgbox_notify import push_msgbox_notify_to_agent

if TYPE_CHECKING:
    from app.ws_registry import AgentConnectionRegistry

logger = logging.getLogger(__name__)

_FORBIDDEN: Dict[str, Any] = {"type": "error", "reason": "forbidden"}


def _check_level0(agent_level: int) -> Dict[str, Any] | None:
    return None if agent_level == 0 else _FORBIDDEN


# ---------------------------------------------------------------------------
# admin_list_agents
# ---------------------------------------------------------------------------

async def handle_admin_list_agents(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    agent_level: int,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    include_revoked: bool = bool(data.get("include_revoked", False))

    async with session_factory() as session:
        query = select(Agent).order_by(Agent.created_at.desc())
        if not include_revoked:
            query = query.where(Agent.revoked_at.is_(None))
        rows = (await session.execute(query)).scalars().all()

    agents = []
    for a in rows:
        connection_id = await registry.get_connection_id(a.agent_id)
        agents.append({
            "agent_id": a.agent_id,
            "agent_name": a.agent_name,
            "level": a.level,
            "label": a.label,
            "revoked_at": a.revoked_at.isoformat() if a.revoked_at else None,
            "created_at": a.created_at.isoformat(),
            "connected": connection_id is not None,
        })

    return {"type": "admin_list_agents_ok", "agents": agents, "total": len(agents)}


# ---------------------------------------------------------------------------
# admin_revoke_agent
# ---------------------------------------------------------------------------

class _RevokePayload(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80)


async def handle_admin_revoke_agent(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    sovereign_agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _RevokePayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_admin_revoke_agent_payload", "detail": exc.errors()}

    target_id = payload.agent_id.strip()
    if target_id == sovereign_agent_id:
        return {"type": "error", "reason": "cannot_revoke_self"}

    async with session_factory() as session:
        target = await session.scalar(select(Agent).where(Agent.agent_id == target_id))
        if target is None:
            return {"type": "error", "reason": "agent_not_found"}
        if target.revoked_at is not None:
            return {"type": "error", "reason": "already_revoked"}
        now = datetime.now(timezone.utc)
        target.revoked_at = now
        await session.commit()

    await registry.force_disconnect(
        target_id,
        {"type": "session_closed", "reason": "revoked"},
        4403,
        "revoked",
    )
    await record_agent_event(
        session_factory,
        event="admin_revoke_agent_via_ws",
        agent_id=target_id,
        connection_id=connection_id,
        detail={"revoked_by": sovereign_agent_id},
    )
    return {
        "type": "admin_revoke_agent_ok",
        "agent_id": target_id,
        "revoked_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# admin_rotate_token
# ---------------------------------------------------------------------------

class _RotatePayload(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80)


async def handle_admin_rotate_token(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    sovereign_agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _RotatePayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_admin_rotate_token_payload", "detail": exc.errors()}

    target_id = payload.agent_id.strip()

    async with session_factory() as session:
        target = await session.scalar(select(Agent).where(Agent.agent_id == target_id))
        if target is None:
            return {"type": "error", "reason": "agent_not_found"}
        new_token = generate_token()
        target.token_hash = sha256_hex(new_token)
        target.token_plaintext = new_token
        target.revoked_at = None
        await session.commit()

    await registry.force_disconnect(
        target_id,
        {"type": "session_closed", "reason": "token_rotated"},
        4001,
        "token_rotated",
    )
    await record_agent_event(
        session_factory,
        event="admin_rotate_token_via_ws",
        agent_id=target_id,
        connection_id=connection_id,
        detail={"rotated_by": sovereign_agent_id},
    )
    return {
        "type": "admin_rotate_token_ok",
        "agent_id": target_id,
        "token": new_token,
    }


# ---------------------------------------------------------------------------
# admin_set_permission
# ---------------------------------------------------------------------------

class _SetPermissionPayload(BaseModel):
    module: str = Field(min_length=1, max_length=60)
    action: str = Field(min_length=1, max_length=60)
    max_level: int = Field(ge=0, le=9)
    limit_value: int | None = None
    description: str | None = Field(default=None, max_length=500)


async def handle_admin_set_permission(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    sovereign_agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _SetPermissionPayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_admin_set_permission_payload", "detail": exc.errors()}

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        row = await session.scalar(
            select(LevelPermission).where(
                LevelPermission.module == payload.module,
                LevelPermission.action == payload.action,
            )
        )
        if row is None:
            row = LevelPermission(
                module=payload.module,
                action=payload.action,
                max_level=payload.max_level,
                limit_value=payload.limit_value,
                description=payload.description,
                updated_at=now,
            )
            session.add(row)
        else:
            row.max_level = payload.max_level
            row.limit_value = payload.limit_value
            row.description = payload.description
            row.updated_at = now
        await session.commit()

    await record_agent_event(
        session_factory,
        event="admin_set_permission_via_ws",
        agent_id=sovereign_agent_id,
        connection_id=connection_id,
        detail={
            "module": payload.module,
            "action": payload.action,
            "max_level": payload.max_level,
        },
    )
    return {
        "type": "admin_set_permission_ok",
        "module": payload.module,
        "action": payload.action,
        "max_level": payload.max_level,
        "limit_value": payload.limit_value,
    }


# ---------------------------------------------------------------------------
# admin_send_directive
# ---------------------------------------------------------------------------

class _SendDirectivePayload(BaseModel):
    to_agent_id: str = Field(min_length=1, max_length=80)
    subject: str | None = Field(default=None, max_length=120)
    body: str = Field(min_length=1, max_length=4000)
    priority: int = Field(default=1, ge=1, le=3)


async def handle_admin_send_directive(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    sovereign_agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _SendDirectivePayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_admin_send_directive_payload", "detail": exc.errors()}

    to_agent_id = payload.to_agent_id.strip()

    async with session_factory() as session:
        recipient = await session.scalar(select(Agent).where(Agent.agent_id == to_agent_id))
        if recipient is None or recipient.revoked_at is not None:
            return {"type": "error", "reason": "unknown_recipient"}

    preview = payload.body.strip()[:100] + ("…" if len(payload.body.strip()) > 100 else "")
    msg_payload: Dict[str, Any] = {"preview": preview, "body": payload.body.strip()}
    if payload.subject:
        msg_payload["subject"] = payload.subject.strip()

    message_id = await push_message(
        session_factory,
        scope="agent",
        recipient_id=to_agent_id,
        from_type="sovereign",
        from_agent_id=sovereign_agent_id,
        type="sovereign_directive",
        priority=payload.priority,
        payload=msg_payload,
    )
    if message_id is None:
        return {"type": "error", "reason": "internal_error"}

    await record_agent_event(
        session_factory,
        event="admin_directive_sent_via_ws",
        agent_id=sovereign_agent_id,
        connection_id=connection_id,
        detail={"to_agent_id": to_agent_id, "message_id": message_id},
    )

    asyncio.create_task(
        push_msgbox_notify_to_agent(
            registry,
            to_agent_id,
            kind="sovereign_directive",
            message_id=message_id,
            from_agent_id=sovereign_agent_id,
            preview=preview,
        )
    )

    return {
        "type": "admin_send_directive_ok",
        "message_id": message_id,
        "to_agent_id": to_agent_id,
    }


# ---------------------------------------------------------------------------
# admin_list_permissions
# ---------------------------------------------------------------------------

async def handle_admin_list_permissions(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    agent_level: int,
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    async with session_factory() as session:
        rows = (await session.execute(
            select(LevelPermission).order_by(LevelPermission.module, LevelPermission.action)
        )).scalars().all()

    return {
        "type": "admin_list_permissions_ok",
        "permissions": [
            {
                "module": r.module,
                "action": r.action,
                "max_level": r.max_level,
                "limit_value": r.limit_value,
                "description": r.description,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ---------------------------------------------------------------------------
# admin_set_agent_level
# ---------------------------------------------------------------------------

class _SetAgentLevelPayload(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80)
    level: int = Field(ge=0, le=9)


async def handle_admin_set_agent_level(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    sovereign_agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _SetAgentLevelPayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_admin_set_agent_level_payload", "detail": exc.errors()}

    target_id = payload.agent_id.strip()
    if target_id == sovereign_agent_id:
        return {"type": "error", "reason": "cannot_change_own_level"}

    async with session_factory() as session:
        target = await session.scalar(select(Agent).where(Agent.agent_id == target_id))
        if target is None:
            return {"type": "error", "reason": "agent_not_found"}
        if target.revoked_at is not None:
            return {"type": "error", "reason": "agent_is_revoked"}
        old_level = target.level
        target.level = payload.level
        await session.commit()

    await record_agent_event(
        session_factory,
        event="admin_set_agent_level_via_ws",
        agent_id=target_id,
        connection_id=connection_id,
        detail={"set_by": sovereign_agent_id, "old_level": old_level, "new_level": payload.level},
    )
    return {
        "type": "admin_set_agent_level_ok",
        "agent_id": target_id,
        "old_level": old_level,
        "new_level": payload.level,
    }


# ---------------------------------------------------------------------------
# admin_set_webhook
# ---------------------------------------------------------------------------

class _SetWebhookPayload(BaseModel):
    agent_id: str = Field(min_length=1, max_length=80)
    social_webhook_url: str | None = Field(default=None, max_length=2000)


async def handle_admin_set_webhook(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    sovereign_agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _SetWebhookPayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_admin_set_webhook_payload", "detail": exc.errors()}

    target_id = payload.agent_id.strip()
    url = payload.social_webhook_url
    if url is not None:
        url = url.strip()
        if url and not (url.startswith("http://") or url.startswith("https://")):
            return {"type": "error", "reason": "invalid_admin_set_webhook_payload",
                    "detail": "social_webhook_url must start with http:// or https://"}

    async with session_factory() as session:
        target = await session.scalar(select(Agent).where(Agent.agent_id == target_id))
        if target is None:
            return {"type": "error", "reason": "agent_not_found"}
        target.social_webhook_url = url or None
        await session.commit()

    await record_agent_event(
        session_factory,
        event="admin_set_webhook_via_ws",
        agent_id=target_id,
        connection_id=connection_id,
        detail={"set_by": sovereign_agent_id, "has_url": bool(url)},
    )
    return {
        "type": "admin_set_webhook_ok",
        "agent_id": target_id,
        "social_webhook_url": url or None,
    }


# ---------------------------------------------------------------------------
# admin_list_articles
# ---------------------------------------------------------------------------

class _ListArticlesPayload(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    publisher_agent_id: str | None = None
    before_id: str | None = None


async def handle_admin_list_articles(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    agent_level: int,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _ListArticlesPayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_admin_list_articles_payload", "detail": exc.errors()}

    async with session_factory() as session:
        query = (
            select(NewsArticle, Agent)
            .outerjoin(Agent, NewsArticle.publisher_agent_id == Agent.agent_id)
            .order_by(NewsArticle.published_at.desc(), NewsArticle.created_at.desc())
        )
        if payload.publisher_agent_id:
            query = query.where(NewsArticle.publisher_agent_id == payload.publisher_agent_id.strip())
        if payload.before_id:
            try:
                before_uuid = uuid.UUID(payload.before_id)
                subq = select(NewsArticle.published_at).where(
                    NewsArticle.id == before_uuid
                ).scalar_subquery()
                query = query.where(NewsArticle.published_at < subq)
            except ValueError:
                pass
        query = query.limit(payload.limit)
        rows = (await session.execute(query)).all()

    def _pub_name(art: NewsArticle, ag: Agent | None) -> str:
        if ag is not None:
            return ag.agent_name
        pid = art.publisher_agent_id
        return (pid[:8] + "…") if len(pid) > 8 else pid

    return {
        "type": "admin_list_articles_ok",
        "articles": [
            {
                "article_id": str(art.id),
                "title": art.title,
                "publisher_agent_id": art.publisher_agent_id,
                "publisher_agent_name": _pub_name(art, ag),
                "tags": art.tags,
                "published_at": art.published_at.isoformat(),
                "like_count": art.like_count,
                "category": {
                    "primary": art.category_level1,
                    "secondary": art.category_level2,
                },
            }
            for art, ag in rows
        ],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# admin_set_article_category
# ---------------------------------------------------------------------------

class _SetArticleCategoryPayload(BaseModel):
    article_id: str = Field(min_length=1, max_length=80)
    category: dict[str, str | None] | None = None


async def handle_admin_set_article_category(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    sovereign_agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _SetArticleCategoryPayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_admin_set_article_category_payload", "detail": exc.errors()}

    try:
        article_uuid = uuid.UUID(payload.article_id)
    except ValueError:
        return {"type": "error", "reason": "invalid_admin_set_article_category_payload",
                "detail": "article_id must be a valid UUID"}

    raw_category = payload.category or {}
    category_level1_raw = raw_category.get("primary")
    category_level2_raw = raw_category.get("secondary")
    if category_level1_raw is not None and not isinstance(category_level1_raw, str):
        return {"type": "error", "reason": "invalid_admin_set_article_category_payload",
                "detail": "category.primary must be a string or null"}
    if category_level2_raw is not None and not isinstance(category_level2_raw, str):
        return {"type": "error", "reason": "invalid_admin_set_article_category_payload",
                "detail": "category.secondary must be a string or null"}
    category_level1 = category_level1_raw.strip() if isinstance(category_level1_raw, str) and category_level1_raw.strip() else None
    category_level2 = category_level2_raw.strip() if isinstance(category_level2_raw, str) and category_level2_raw.strip() else None
    if category_level1 and len(category_level1) > 60:
        return {"type": "error", "reason": "invalid_admin_set_article_category_payload",
                "detail": "category.primary max length is 60"}
    if category_level2 and len(category_level2) > 60:
        return {"type": "error", "reason": "invalid_admin_set_article_category_payload",
                "detail": "category.secondary max length is 60"}

    async with session_factory() as session:
        article = await session.scalar(
            select(NewsArticle).where(NewsArticle.id == article_uuid)
        )
        if article is None:
            return {"type": "error", "reason": "article_not_found"}
        article.category_level1 = category_level1
        article.category_level2 = category_level2
        await session.commit()

    await record_agent_event(
        session_factory,
        event="admin_set_article_category_via_ws",
        agent_id=sovereign_agent_id,
        connection_id=connection_id,
        detail={
            "article_id": payload.article_id,
            "category_level1": category_level1,
            "category_level2": category_level2,
        },
    )
    return {
        "type": "admin_set_article_category_ok",
        "article_id": payload.article_id,
        "category": {
            "primary": category_level1,
            "secondary": category_level2,
        },
    }


# ---------------------------------------------------------------------------
# admin_moderate_article
# ---------------------------------------------------------------------------

class _ModerateArticlePayload(BaseModel):
    article_id: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=10, max_length=500)


async def handle_admin_moderate_article(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    sovereign_agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
    news_markdown_root: str = "",
) -> Dict[str, Any]:
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _ModerateArticlePayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_admin_moderate_article_payload", "detail": exc.errors()}

    try:
        article_uuid = uuid.UUID(payload.article_id)
    except ValueError:
        return {"type": "error", "reason": "invalid_admin_moderate_article_payload",
                "detail": "article_id must be a valid UUID"}

    async with session_factory() as session:
        article = await session.scalar(
            select(NewsArticle).where(NewsArticle.id == article_uuid)
        )
        if article is None:
            return {"type": "error", "reason": "article_not_found"}

        author_id = article.publisher_agent_id
        title = article.title
        markdown_path = article.markdown_path

        await session.delete(article)
        await session.commit()

    if news_markdown_root and markdown_path:
        try:
            md_file = resolve_markdown_path(markdown_path, news_markdown_root)
            if md_file.is_file():
                md_file.unlink()
        except Exception:
            logger.warning(
                "admin_moderate_article: could not delete markdown file path=%s", markdown_path
            )

    message_id = await push_message(
        session_factory,
        scope="agent",
        recipient_id=author_id,
        from_type="sovereign",
        from_agent_id=sovereign_agent_id,
        type="article_moderated",
        priority=1,
        resource_type="article",
        resource_id=payload.article_id,
        payload={"title": title, "action": "removed", "reason": payload.reason.strip()},
    )
    if message_id:
        asyncio.create_task(
            push_msgbox_notify_to_agent(
                registry,
                author_id,
                kind="article_moderated",
                message_id=message_id,
                extra={
                    "article_id": payload.article_id,
                    "title": title,
                    "action": "removed",
                },
            )
        )

    await record_agent_event(
        session_factory,
        event="admin_moderate_article_via_ws",
        agent_id=sovereign_agent_id,
        connection_id=connection_id,
        detail={
            "article_id": payload.article_id,
            "title": title,
            "author_agent_id": author_id,
            "reason": payload.reason.strip(),
        },
    )
    return {
        "type": "admin_moderate_article_ok",
        "article_id": payload.article_id,
        "title": title,
        "author_agent_id": author_id,
    }


# ---------------------------------------------------------------------------
# admin_dissolve_social_room
# ---------------------------------------------------------------------------

class _DissolveSocialRoomPayload(BaseModel):
    room_id: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)


async def handle_admin_dissolve_social_room(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    social: Any,
    settings: Any,
    sovereign_agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Force-dissolve an active A2A chat room. Permanent rooms (check-in) are protected."""
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _DissolveSocialRoomPayload(**data)
    except ValidationError:
        return {"type": "error", "reason": "invalid_admin_dissolve_social_room_payload"}

    from app.social_registry import CHECKIN_ROOM_ID
    if payload.room_id == CHECKIN_ROOM_ID:
        return {"type": "error", "reason": "cannot_dissolve_checkin_room"}

    room = await social.force_dissolve(payload.room_id)
    if room is None:
        return {"type": "error", "reason": "room_not_found"}

    now = datetime.now(timezone.utc)
    member_ids = list(room.members.keys())

    await social.broadcast_dissolution(room, reason="admin_dissolve")

    from app.domains.social.persistence.social_repository import record_room_dissolved
    await record_room_dissolved(
        session_factory,
        room_id=room.room_id,
        reason="admin_dissolve",
        total_messages=room.message_count,
        dissolved_at=now,
        member_ids=member_ids,
    )

    await record_agent_event(
        session_factory,
        event="admin_dissolve_social_room_via_ws",
        agent_id=sovereign_agent_id,
        connection_id=connection_id,
        detail={
            "room_id": room.room_id,
            "name": room.name,
            "member_count": len(member_ids),
            "note": payload.note.strip(),
        },
    )

    from app.services.social_notify import build_room_dissolved_notify, schedule_social_notify
    if member_ids and settings is not None:
        ws_body, hook_payload = build_room_dissolved_notify(
            room_id=room.room_id,
            room_name=room.name,
            reason="admin_dissolve",
        )
        schedule_social_notify(
            session_factory=session_factory,
            registry=registry,
            settings=settings,
            recipient_agent_ids=member_ids,
            ws_body=ws_body,
            webhook_event="social.room_dissolved",
            webhook_payload=hook_payload,
        )

    return {
        "type": "admin_dissolve_social_room_ok",
        "room_id": room.room_id,
        "name": room.name,
        "dissolved_at": now.isoformat(),
        "member_count": len(member_ids),
    }


# ---------------------------------------------------------------------------
# admin_resurrect_social_room
# ---------------------------------------------------------------------------

class _ResurrectSocialRoomPayload(BaseModel):
    room_id: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)


async def handle_admin_resurrect_social_room(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    social: Any,
    sovereign_agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Re-open a dissolved room: clear DB dissolution and load an empty in-memory room."""
    err = _check_level0(agent_level)
    if err:
        return err

    try:
        payload = _ResurrectSocialRoomPayload(**data)
    except ValidationError:
        return {"type": "error", "reason": "invalid_admin_resurrect_social_room_payload"}

    if social is None:
        return {"type": "error", "reason": "social_unavailable"}

    existing = await social.get_room(payload.room_id)
    if existing is not None:
        return {"type": "error", "reason": "room_already_active"}

    from app.services.display_name_resolve import load_agent_name_map
    from app.domains.social.persistence.social_repository import record_room_reopened
    from app.social_registry import chat_room_from_social_row

    row, reopen_err = await record_room_reopened(session_factory, payload.room_id)
    if reopen_err == "not_found":
        return {"type": "error", "reason": "room_not_found"}
    if reopen_err == "not_dissolved":
        return {"type": "error", "reason": "room_not_dissolved"}
    assert row is not None

    async with session_factory() as session:
        cids = (
            [row.creator_agent_id]
            if row.creator_agent_id and row.creator_agent_id != "system"
            else []
        )
        nmap = await load_agent_name_map(session, cids) if cids else {}
    if row.creator_agent_id == "system":
        creator_display = "system"
    else:
        creator_display = nmap.get(row.creator_agent_id) or (
            (row.creator_agent_id[:8] + "…")
            if len(row.creator_agent_id) > 8
            else row.creator_agent_id
        )
    room = chat_room_from_social_row(
        row, creator_name=creator_display, agent_cap=social.max_concurrent_agents
    )
    if not await social.register_resurrected_room(room):
        return {"type": "error", "reason": "room_already_active"}

    await record_agent_event(
        session_factory,
        event="admin_resurrect_social_room_via_ws",
        agent_id=sovereign_agent_id,
        connection_id=connection_id,
        detail={
            "room_id": room.room_id,
            "name": room.name,
            "note": payload.note.strip(),
        },
    )

    return {
        "type": "admin_resurrect_social_room_ok",
        "room_id": room.room_id,
        "name": room.name,
        "topic": room.topic,
        "rules": room.rules or "",
        "creator_id": room.creator_id,
        "created_at": room.created_at.isoformat(),
        "total_messages": room.message_count,
    }
