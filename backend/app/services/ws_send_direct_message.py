"""
Handle the send_direct_message WebSocket frame.

Agent → Server:
  { "type": "send_direct_message", "to_agent_id": "agt_xxx",
    "subject": "optional", "body": "..." }

Server → Agent (success):
  { "type": "send_direct_message_ok", "message_id": "<uuid>", "to_agent_id": "agt_xxx" }

The message is persisted to agent_messages and, if the recipient is currently
connected on /v2/agent/ws, a push frame is sent to notify them immediately.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent
from app.services.agent_event_log import record_agent_event
from app.services.msgbox import push_message

if TYPE_CHECKING:
    from app.ws_registry import AgentConnectionRegistry

logger = logging.getLogger(__name__)

_BODY_MIN = 1
_BODY_MAX = 4000
_SUBJECT_MAX = 120
_PREVIEW_MAX = 100


class SendDirectMessagePayload(BaseModel):
    to_agent_id: str = Field(min_length=1, max_length=80)
    subject: Optional[str] = Field(default=None, max_length=_SUBJECT_MAX)
    body: str = Field(min_length=_BODY_MIN, max_length=_BODY_MAX)


def _preview(text: str) -> str:
    t = text.strip()
    return t if len(t) <= _PREVIEW_MAX else t[:_PREVIEW_MAX] + "…"


async def handle_send_direct_message_ws_message(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    agent_id: str,
    connection_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Persist a direct message to the recipient's inbox and optionally push
    a live notification if the recipient is currently connected.
    Returns a dict to send as one WebSocket text frame.
    """
    try:
        payload = SendDirectMessagePayload.model_validate(data)
    except ValidationError as exc:
        return {
            "type": "error",
            "reason": "invalid_send_direct_message_payload",
            "detail": exc.errors(),
        }

    to_agent_id = payload.to_agent_id.strip()

    if to_agent_id == agent_id:
        return {"type": "error", "reason": "cannot_dm_self"}

    # Resolve sender name and verify recipient exists.
    async with session_factory() as session:
        sender = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
        if sender is None:
            return {"type": "error", "reason": "unknown_agent"}

        recipient = await session.scalar(select(Agent).where(Agent.agent_id == to_agent_id))
        if recipient is None:
            return {"type": "error", "reason": "unknown_recipient"}
        if recipient.revoked_at is not None:
            return {"type": "error", "reason": "unknown_recipient"}

    from_type = "sovereign" if sender.level == 0 else "agent"
    msg_payload: dict[str, Any] = {
        "preview": _preview(payload.body),
        "body": payload.body.strip(),
    }
    if payload.subject:
        msg_payload["subject"] = payload.subject.strip()

    message_id = await push_message(
        session_factory,
        scope="agent",
        recipient_id=to_agent_id,
        from_type=from_type,
        from_agent_id=agent_id,
        from_name=sender.agent_name,
        type="direct_message",
        priority=1 if sender.is_sovereign else 2,
        payload=msg_payload,
    )

    if message_id is None:
        return {"type": "error", "reason": "internal_error"}

    await record_agent_event(
        session_factory,
        event="msgbox_dm_sent",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={"to_agent_id": to_agent_id, "message_id": message_id},
    )

    # Best-effort live push to recipient if connected.
    push_body = {
        "type": "msgbox_notify",
        "kind": "direct_message",
        "message_id": message_id,
        "from_agent_id": agent_id,
        "from_name": sender.agent_name,
        "preview": msg_payload["preview"],
    }
    asyncio.create_task(_push_notify(registry, to_agent_id, push_body))

    return {
        "type": "send_direct_message_ok",
        "message_id": message_id,
        "to_agent_id": to_agent_id,
    }


async def _push_notify(
    registry: "AgentConnectionRegistry",
    agent_id: str,
    body: dict[str, Any],
) -> None:
    try:
        await registry.send_push(agent_id, body)
    except Exception:
        logger.exception("ws_send_direct_message: live push failed agent_id=%s", agent_id)
