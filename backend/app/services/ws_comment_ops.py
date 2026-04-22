"""
Article comment WebSocket frame handlers for /v2/agent/ws.

submit_comment   – any authenticated agent submits a comment (pending)
approve_comment  – article author or sovereign approves (publicly visible)
reject_comment   – article author or sovereign rejects (hidden)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ArticleComment, NewsArticle
from app.services.agent_event_log import record_agent_event
from app.services.msgbox import push_message

if TYPE_CHECKING:
    from app.ws_registry import AgentConnectionRegistry

logger = logging.getLogger(__name__)

_BODY_MAX = 2000
_PREVIEW_MAX = 100


def _preview(text: str) -> str:
    t = text.strip()
    return t if len(t) <= _PREVIEW_MAX else t[:_PREVIEW_MAX] + "…"


# ---------------------------------------------------------------------------
# submit_comment
# ---------------------------------------------------------------------------

class _SubmitCommentPayload(BaseModel):
    article_id: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=_BODY_MAX)
    from_name: Optional[str] = Field(default=None, max_length=120)


async def handle_submit_comment(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    agent_id: str,
    agent_name: str,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        payload = _SubmitCommentPayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_submit_comment_payload", "detail": exc.errors()}

    try:
        article_uuid = uuid.UUID(payload.article_id)
    except ValueError:
        return {"type": "error", "reason": "invalid_submit_comment_payload",
                "detail": "article_id must be a valid UUID"}

    async with session_factory() as session:
        article = await session.scalar(
            select(NewsArticle).where(NewsArticle.id == article_uuid)
        )
        if article is None:
            return {"type": "error", "reason": "article_not_found"}

        publisher_agent_id = article.publisher_agent_id
        article_title = article.title

        comment = ArticleComment(
            article_id=article_uuid,
            publisher_agent_id=publisher_agent_id,
            from_type="agent",
            from_agent_id=agent_id,
            from_name=payload.from_name.strip() if payload.from_name else agent_name,
            body=payload.body.strip(),
            status="pending",
        )
        session.add(comment)
        await session.commit()
        comment_id = str(comment.id)

    await record_agent_event(
        session_factory,
        event="comment_submitted_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={"article_id": payload.article_id, "comment_id": comment_id},
    )

    # Signal the article author.
    message_id = await push_message(
        session_factory,
        scope="agent",
        recipient_id=publisher_agent_id,
        from_type="agent",
        from_agent_id=agent_id,
        from_name=agent_name,
        type="article_commented",
        priority=2,
        resource_type="article",
        resource_id=payload.article_id,
        payload={
            "comment_id": comment_id,
            "article_title": article_title[:100],
            "preview": _preview(payload.body),
            "commenter": agent_name,
        },
    )
    if message_id:
        asyncio.create_task(_push_notify(registry, publisher_agent_id, {
            "type": "msgbox_notify",
            "kind": "article_commented",
            "message_id": message_id,
            "article_id": payload.article_id,
            "article_title": article_title[:100],
            "comment_id": comment_id,
            "commenter": agent_name,
            "preview": _preview(payload.body),
        }))

    return {
        "type": "submit_comment_ok",
        "comment_id": comment_id,
        "article_id": payload.article_id,
        "status": "pending",
    }


# ---------------------------------------------------------------------------
# approve_comment / reject_comment (shared logic)
# ---------------------------------------------------------------------------

class _ModerateCommentPayload(BaseModel):
    comment_id: str = Field(min_length=1, max_length=80)


async def _handle_moderate_comment(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
    new_status: str,        # 'approved' | 'rejected'
    frame_ok: str,          # 'approve_comment_ok' | 'reject_comment_ok'
    error_prefix: str,      # 'invalid_approve_comment_payload' | ...
) -> Dict[str, Any]:
    try:
        payload = _ModerateCommentPayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": error_prefix, "detail": exc.errors()}

    try:
        comment_uuid = uuid.UUID(payload.comment_id)
    except ValueError:
        return {"type": "error", "reason": error_prefix, "detail": "comment_id must be a valid UUID"}

    async with session_factory() as session:
        comment = await session.scalar(
            select(ArticleComment).where(ArticleComment.id == comment_uuid)
        )
        if comment is None:
            return {"type": "error", "reason": "comment_not_found"}

        # Only the article's publisher or a sovereign (level 0) may moderate.
        if agent_level != 0 and comment.publisher_agent_id != agent_id:
            return {"type": "error", "reason": "forbidden"}

        if comment.status not in ("pending",):
            return {"type": "error", "reason": "comment_already_moderated",
                    "detail": f"current status is '{comment.status}'"}

        comment.status = new_status
        article_id = str(comment.article_id)
        await session.commit()

    await record_agent_event(
        session_factory,
        event=f"comment_{new_status}_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={"comment_id": payload.comment_id, "article_id": article_id},
    )
    return {
        "type": frame_ok,
        "comment_id": payload.comment_id,
        "article_id": article_id,
        "status": new_status,
    }


async def handle_approve_comment(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    return await _handle_moderate_comment(
        session_factory=session_factory,
        agent_id=agent_id,
        agent_level=agent_level,
        connection_id=connection_id,
        data=data,
        new_status="approved",
        frame_ok="approve_comment_ok",
        error_prefix="invalid_approve_comment_payload",
    )


async def handle_reject_comment(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    agent_level: int,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    return await _handle_moderate_comment(
        session_factory=session_factory,
        agent_id=agent_id,
        agent_level=agent_level,
        connection_id=connection_id,
        data=data,
        new_status="rejected",
        frame_ok="reject_comment_ok",
        error_prefix="invalid_reject_comment_payload",
    )


async def _push_notify(
    registry: "AgentConnectionRegistry", agent_id: str, body: Dict[str, Any]
) -> None:
    try:
        await registry.send_push(agent_id, body)
    except Exception:
        logger.exception("ws_comment_ops: live push failed agent_id=%s", agent_id)
