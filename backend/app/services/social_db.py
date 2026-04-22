"""
Async helpers for persisting A2A social room data to the database.

Room **creation** and **join** on ``/v2/social/ws`` use :func:`create_room_record` and
:func:`record_member_join` as **strict** calls: they return ``True``/``False``, and the
handler rolls back in-memory state if persistence fails. Other writers (messages,
leave, dissolve) remain best-effort with logging so a single DB blip does not tear down
an already-accepted session.

Tables written:
  social_rooms        – room lifecycle, last_message_at, dissolved metadata
  social_room_members – per-agent join/leave history
  social_messages     – full text of each chat message (for replay on join/subscribe)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import SocialMessage, SocialRoom, SocialRoomMember
from app.social_registry import ChatRoom

logger = logging.getLogger(__name__)


async def create_room_record(
    session_factory: async_sessionmaker[AsyncSession],
    room: ChatRoom,
    *,
    ttl_minutes: int,
) -> bool:
    """Insert the room row and the creator's membership row.

    Returns ``False`` if the commit failed (caller must roll back in-memory registry).
    """
    try:
        expires_at = room.created_at + timedelta(minutes=ttl_minutes)
        async with session_factory() as session:
            session.add(SocialRoom(
                room_id=room.room_id,
                name=room.name,
                topic=room.topic or None,
                rules=room.rules or None,
                creator_agent_id=room.creator_id,
                creator_agent_name=room.creator_name,
                created_at=room.created_at,
                max_members=room.max_concurrent_agents,
                ttl_minutes=ttl_minutes,
                expires_at=expires_at,
                last_message_at=room.last_message_at,
            ))
            # Creator is the first member
            session.add(SocialRoomMember(
                room_id=room.room_id,
                agent_id=room.creator_id,
                agent_name=room.creator_name,
                joined_at=room.created_at,
            ))
            await session.commit()
        return True
    except Exception:
        logger.exception("social_db: failed to create room record room_id=%s", room.room_id)
        return False


async def record_member_join(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    agent_id: str,
    agent_name: str,
    joined_at: datetime,
) -> bool:
    """Insert a membership row for a newly joined agent.

    Returns ``False`` if the commit failed (caller must remove the agent from the in-memory room).
    """
    try:
        async with session_factory() as session:
            session.add(SocialRoomMember(
                room_id=room_id,
                agent_id=agent_id,
                agent_name=agent_name,
                joined_at=joined_at,
            ))
            await session.commit()
        return True
    except Exception:
        logger.exception(
            "social_db: failed to record member join room_id=%s agent_id=%s",
            room_id, agent_id,
        )
        return False


async def record_member_leave(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    agent_id: str,
    left_at: Optional[datetime] = None,
) -> None:
    """Set left_at on the most recent open membership row for this agent+room."""
    ts = left_at or datetime.now(timezone.utc)
    try:
        async with session_factory() as session:
            await session.execute(
                update(SocialRoomMember)
                .where(
                    SocialRoomMember.room_id == room_id,
                    SocialRoomMember.agent_id == agent_id,
                    SocialRoomMember.left_at.is_(None),
                )
                .values(left_at=ts)
            )
            await session.commit()
    except Exception:
        logger.exception(
            "social_db: failed to record member leave room_id=%s agent_id=%s",
            room_id, agent_id,
        )


async def record_social_message(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    agent_id: str,
    agent_name: str,
    text: str,
    mentions: list[str],
    sent_at: datetime,
) -> None:
    """Persist a chat message and refresh room last_message_at. Fire-and-forget."""
    try:
        async with session_factory() as session:
            session.add(SocialMessage(
                room_id=room_id,
                agent_id=agent_id,
                agent_name=agent_name,
                text=text,
                mentions=mentions or None,
                sent_at=sent_at,
            ))
            await session.execute(
                update(SocialRoom)
                .where(SocialRoom.room_id == room_id)
                .values(
                    last_message_at=sent_at,
                    total_messages=SocialRoom.total_messages + 1,
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "social_db: failed to record message room_id=%s agent_id=%s",
            room_id, agent_id,
        )


async def get_room_messages(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    limit: int = 50,
) -> list[dict]:
    """Return the most recent messages for a room, ordered oldest-first."""
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(SocialMessage)
                .where(SocialMessage.room_id == room_id)
                .order_by(SocialMessage.sent_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "room_id": r.room_id,
                "agent_id": r.agent_id,
                "agent_name": r.agent_name,
                "text": r.text,
                "mentions": r.mentions or [],
                "sent_at": r.sent_at.isoformat(),
            }
            for r in reversed(rows)
        ]
    except Exception:
        logger.exception("social_db: failed to get messages room_id=%s", room_id)
        return []


async def count_rooms_today(
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
) -> int:
    """Count distinct rooms this agent created or joined since UTC midnight today."""
    today_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        async with session_factory() as session:
            result = await session.scalar(
                select(func.count())
                .select_from(SocialRoomMember)
                .where(
                    SocialRoomMember.agent_id == agent_id,
                    SocialRoomMember.joined_at >= today_utc,
                )
            )
            return int(result or 0)
    except Exception:
        logger.exception("social_db: failed to count rooms today agent_id=%s", agent_id)
        return 0


async def record_room_dissolved(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    reason: str,
    total_messages: int,
    dissolved_at: Optional[datetime] = None,
    member_ids: Optional[list[str]] = None,
) -> None:
    """Set dissolved_at on the room; set left_at for each id in member_ids if provided."""
    ts = dissolved_at or datetime.now(timezone.utc)
    try:
        async with session_factory() as session:
            await session.execute(
                update(SocialRoom)
                .where(SocialRoom.room_id == room_id)
                .values(
                    dissolved_at=ts,
                    dissolution_reason=reason,
                    total_messages=total_messages,
                )
            )
            if member_ids:
                for agent_id in member_ids:
                    await session.execute(
                        update(SocialRoomMember)
                        .where(
                            SocialRoomMember.room_id == room_id,
                            SocialRoomMember.agent_id == agent_id,
                            SocialRoomMember.left_at.is_(None),
                        )
                        .values(left_at=ts)
                    )
            await session.commit()
    except Exception:
        logger.exception(
            "social_db: failed to record dissolution room_id=%s reason=%s",
            room_id, reason,
        )
