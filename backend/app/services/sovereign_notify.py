"""
Best-effort WebSocket push to all non-revoked level-0 (sovereign) agents.

Used when a new global msgbox row is created so online L0 agents see msgbox_notify
without waiting for the next HTTP poll. Does not change msgbox persistence semantics.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from app.ws_registry import AgentConnectionRegistry

from app.models import Agent
from app.services.msgbox_notify import build_msgbox_notify_payload

logger = logging.getLogger(__name__)


async def push_msgbox_notify_to_sovereigns(
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    *,
    message_id: str,
    kind: str,
    preview: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """
    Fire ``msgbox_notify`` to every connected sovereign agent. Safe to call from
    create paths; errors are logged and not re-raised.
    """
    body = build_msgbox_notify_payload(
        kind=kind,
        message_id=message_id,
        preview=preview,
        extra=extra,
    )
    try:
        async with session_factory() as session:
            sovereign_ids = (
                await session.scalars(
                    select(Agent.agent_id).where(Agent.level == 0, Agent.revoked_at.is_(None))
                )
            ).all()
        for aid in sovereign_ids:
            await registry.send_push(aid, body)
    except Exception:
        logger.exception("sovereign_notify: failed kind=%s message_id=%s", kind, message_id)
