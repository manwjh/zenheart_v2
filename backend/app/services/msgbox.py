"""
Core message-box service.

All public functions are safe to await directly — exceptions are caught and logged
so that a msgbox hiccup never breaks the caller's main flow (following the same
convention as agent_event_log.py).

push_message()   – insert a new message (fire-and-forget safe)
ack_messages()   – mark a list of message IDs as read
get_summary()    – lightweight unread summary (injected into auth_ok)
list_messages()  – paginated message list for the inbox API
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.model_defs import AgentMessage
from app.services.display_name_resolve import load_agent_name_map

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# push_message
# ---------------------------------------------------------------------------

async def push_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    scope: str,                          # 'global' | 'agent'
    recipient_id: Optional[str] = None,  # agent_id; None for scope='global'
    from_type: str,                      # 'system'|'rule_engine'|'sovereign'|'agent'|'anonymous'
    from_agent_id: Optional[str] = None,
    visitor_from_name: Optional[str] = None,
    type: str,
    priority: int = 2,                   # 1=high 2=normal 3=low
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """
    Insert one AgentMessage row. Returns the new message id (str) or None on error.
    Safe to call fire-and-forget; all DB errors are logged, never re-raised.

    ``visitor_from_name`` is only for anonymous sender display.
    Caller owns payload construction; this function does not mutate payload.
    """
    if visitor_from_name and from_type != "anonymous":
        logger.error(
            "msgbox.push_message invalid args: visitor_from_name requires from_type=anonymous "
            "scope=%s type=%s recipient=%s from_type=%s",
            scope, type, recipient_id, from_type,
        )
        return None
    msg_id = uuid.uuid4()
    pl = dict(payload) if payload else None
    row = AgentMessage(
        id=msg_id,
        scope=scope,
        recipient_id=recipient_id,
        from_type=from_type,
        from_agent_id=from_agent_id,
        visitor_from_name=(visitor_from_name or "").strip() or None,
        type=type,
        priority=priority,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=pl,
    )
    try:
        async with session_factory() as session:
            session.add(row)
            await session.commit()
        return str(msg_id)
    except Exception:
        logger.exception(
            "msgbox.push_message failed scope=%s type=%s recipient=%s",
            scope, type, recipient_id,
        )
        return None


# ---------------------------------------------------------------------------
# ack_messages
# ---------------------------------------------------------------------------

async def ack_messages(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message_ids: list[str],
    scope: str,
    recipient_id: Optional[str] = None,  # None for global scope
) -> int:
    """
    Mark the given message IDs as read for the given scope/recipient.
    Returns the number of rows updated. Logs and returns 0 on error.
    """
    if not message_ids:
        return 0
    try:
        parsed = [uuid.UUID(mid) for mid in message_ids]
    except ValueError:
        logger.warning("msgbox.ack_messages: invalid UUID in message_ids")
        return 0

    now = datetime.now(timezone.utc)
    try:
        async with session_factory() as session:
            if scope == "global":
                condition = and_(
                    AgentMessage.id.in_(parsed),
                    AgentMessage.scope == "global",
                    AgentMessage.read_at.is_(None),
                )
            else:
                condition = and_(
                    AgentMessage.id.in_(parsed),
                    AgentMessage.scope == "agent",
                    AgentMessage.recipient_id == recipient_id,
                    AgentMessage.read_at.is_(None),
                )
            result = await session.execute(
                update(AgentMessage)
                .where(condition)
                .values(read_at=now)
            )
            await session.commit()
            return result.rowcount
    except Exception:
        logger.exception("msgbox.ack_messages failed scope=%s recipient=%s", scope, recipient_id)
        return 0


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------

async def get_summary(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    agent_id: str,
    agent_level: int = 9,
) -> dict[str, Any]:
    """
    Return a lightweight summary for injection into auth_ok.
    Level 0 (sovereign) agents also include the global governance queue unread count.
    """
    is_level0 = agent_level == 0
    try:
        async with session_factory() as session:
            private_count = await session.scalar(
                select(func.count(AgentMessage.id)).where(
                    AgentMessage.scope == "agent",
                    AgentMessage.recipient_id == agent_id,
                    AgentMessage.read_at.is_(None),
                )
            ) or 0

            top_row = await session.scalar(
                select(AgentMessage).where(
                    AgentMessage.scope == "agent",
                    AgentMessage.recipient_id == agent_id,
                    AgentMessage.read_at.is_(None),
                ).order_by(AgentMessage.priority.asc(), AgentMessage.created_at.desc()).limit(1)
            )

            global_count = 0
            if is_level0:
                global_count = await session.scalar(
                    select(func.count(AgentMessage.id)).where(
                        AgentMessage.scope == "global",
                        AgentMessage.read_at.is_(None),
                    )
                ) or 0

        total_unread = private_count + global_count
        summary: dict[str, Any] = {"unread_count": total_unread}
        if total_unread > 0:
            summary["has_high_priority"] = (
                (top_row is not None and top_row.priority == 1) or
                (is_level0 and global_count > 0)
            )
            summary["top_type"] = top_row.type if top_row else None
        return summary
    except Exception:
        logger.exception("msgbox.get_summary failed agent_id=%s", agent_id)
        return {"unread_count": 0}


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------

def _row_to_dict(row: AgentMessage, *, from_name: str | None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "scope": row.scope,
        "recipient_id": row.recipient_id,
        "from_type": row.from_type,
        "from_agent_id": row.from_agent_id,
        "from_name": from_name,
        "type": row.type,
        "priority": row.priority,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "payload": row.payload,
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "created_at": row.created_at.isoformat(),
    }


def _display_name_for_msgbox_row(
    row: AgentMessage, name_by_id: dict[str, str]
) -> str | None:
    if row.from_type == "anonymous":
        return (row.visitor_from_name or "").strip() or "Anonymous"
    if row.from_agent_id:
        n = name_by_id.get(row.from_agent_id)
        if n:
            return n
        vn = (row.visitor_from_name or "").strip()
        if vn:
            return vn
        aid = row.from_agent_id
        return (aid[:8] + "…") if len(aid) > 8 else aid
    pl = row.payload if isinstance(row.payload, dict) else {}
    fl = pl.get("from_label") if isinstance(pl, dict) else None
    if isinstance(fl, str) and fl.strip():
        return fl.strip()
    return (row.visitor_from_name or "").strip() or None


async def list_messages(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    agent_id: str,
    scope: str = "agent",          # 'agent' | 'global'
    unread_only: bool = True,
    limit: int = 20,
    before_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Return messages for the inbox, newest first.
    Default ``unread_only=True`` matches REST: ack'd rows (``read_at`` set) are omitted
    unless the client asks for history with ``unread_only=false``.
    scope='global' is restricted to sovereign agents (caller must verify).
    """
    try:
        if scope == "global":
            base_filter = [AgentMessage.scope == "global"]
        else:
            base_filter = [
                AgentMessage.scope == "agent",
                AgentMessage.recipient_id == agent_id,
            ]

        if unread_only:
            base_filter.append(AgentMessage.read_at.is_(None))

        if before_id:
            try:
                before_uuid = uuid.UUID(before_id)
                subq = select(AgentMessage.created_at).where(
                    AgentMessage.id == before_uuid
                ).scalar_subquery()
                base_filter.append(AgentMessage.created_at < subq)
            except ValueError:
                pass

        async with session_factory() as session:
            result = await session.execute(
                select(AgentMessage)
                .where(*base_filter)
                .order_by(AgentMessage.created_at.desc())
                .limit(min(limit, 100))
            )
            rows = result.scalars().all()
            ids = {r.from_agent_id for r in rows if r.from_agent_id}
            name_map = await load_agent_name_map(session, ids) if ids else {}
            out: list[dict[str, Any]] = []
            for r in rows:
                dname = _display_name_for_msgbox_row(r, name_map)
                out.append(_row_to_dict(r, from_name=dname))
            return out
    except Exception:
        logger.exception("msgbox.list_messages failed agent_id=%s scope=%s", agent_id, scope)
        return []
