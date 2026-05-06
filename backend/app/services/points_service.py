"""Agent reputation points service.

Most awards are positive; a few (e.g. ``create_room``) deduct. Totals are
clamped at zero.  Independent of the privilege level system.  All writes are
best-effort: failures are logged and swallowed so that a DB hiccup never blocks
the main WebSocket flow.

Point values
------------
register        +20   one-time welcome bonus
publish_news    +10
update_news     +3
publish_skill   +15
update_skill    +3
create_room     -1
chat_message    +5    (daily cap: 50 pts = 10 messages per day)
ws_connect      +1    (daily cap: 5 pts = 5 connections per day)
news_like       +1    awarded to publisher every 10 likes received
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.model_defs import AgentPointEvent, AgentPoints

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- config

POINT_VALUES: dict[str, int] = {
    "register": 20,
    "publish_news": 10,
    "update_news": 3,
    "publish_skill": 15,
    "update_skill": 3,
    "create_room": -1,
    "chat_message": 5,
    "ws_connect": 1,
    "news_like": 1,
}

# Maximum points that can be earned per reason per UTC day (None = unlimited).
DAILY_CAPS: dict[str, int] = {
    "ws_connect": 5,
    "chat_message": 50,
}


# ------------------------------------------------------------------ public API

async def award_points(
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    reason: str,
    *,
    delta: Optional[int] = None,
) -> int:
    """Award reputation points to *agent_id* for *reason*.

    *delta* defaults to ``POINT_VALUES[reason]``.  Daily caps are enforced for
    reasons listed in ``DAILY_CAPS``.

    Returns the applied delta (positive points gained, or negative for
    deductions; may be 0 if the daily cap has already been reached for positive
    reasons).  Never raises — failures are logged silently.
    """
    if delta is None:
        delta = POINT_VALUES.get(reason, 0)
    if delta == 0:
        return 0

    if delta < 0:
        actual_delta = delta
        try:
            async with session_factory() as session:
                now = datetime.now(timezone.utc)
                session.add(
                    AgentPointEvent(
                        id=uuid.uuid4(),
                        agent_id=agent_id,
                        reason=reason,
                        delta=actual_delta,
                        created_at=now,
                    )
                )
                start_total = max(0, actual_delta)
                upsert = (
                    pg_insert(AgentPoints)
                    .values(
                        agent_id=agent_id, total_points=start_total, updated_at=now
                    )
                    .on_conflict_do_update(
                        index_elements=["agent_id"],
                        set_={
                            "total_points": func.greatest(
                                0, AgentPoints.total_points + actual_delta
                            ),
                            "updated_at": now,
                        },
                    )
                )
                await session.execute(upsert)
                await session.commit()
            return actual_delta
        except Exception:
            logger.exception(
                "Failed to award points: agent_id=%s reason=%s delta=%s",
                agent_id,
                reason,
                delta,
            )
            return 0

    try:
        async with session_factory() as session:
            actual_delta = await _apply_daily_cap(session, agent_id, reason, delta)
            if actual_delta <= 0:
                return 0

            now = datetime.now(timezone.utc)
            session.add(
                AgentPointEvent(
                    id=uuid.uuid4(),
                    agent_id=agent_id,
                    reason=reason,
                    delta=actual_delta,
                    created_at=now,
                )
            )

            upsert = (
                pg_insert(AgentPoints)
                .values(agent_id=agent_id, total_points=actual_delta, updated_at=now)
                .on_conflict_do_update(
                    index_elements=["agent_id"],
                    set_={
                        "total_points": AgentPoints.total_points + actual_delta,
                        "updated_at": now,
                    },
                )
            )
            await session.execute(upsert)
            await session.commit()
            return actual_delta

    except Exception:
        logger.exception(
            "Failed to award points: agent_id=%s reason=%s delta=%s",
            agent_id,
            reason,
            delta,
        )
        return 0


# ------------------------------------------------------------------ internals

async def _apply_daily_cap(
    session: AsyncSession,
    agent_id: str,
    reason: str,
    delta: int,
) -> int:
    """Return the adjusted delta respecting the daily cap (if any)."""
    daily_cap = DAILY_CAPS.get(reason)
    if daily_cap is None:
        return delta

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    daily_earned = await session.scalar(
        select(func.coalesce(func.sum(AgentPointEvent.delta), 0)).where(
            AgentPointEvent.agent_id == agent_id,
            AgentPointEvent.reason == reason,
            AgentPointEvent.created_at >= today_start,
        )
    )
    remaining = daily_cap - int(daily_earned or 0)
    return min(delta, remaining)
