"""
Async helpers for persisting A2A social room data to the database.

All functions use fire-and-forget semantics (same as agent_event_log):
exceptions are caught and logged so that a DB hiccup never breaks the
WebSocket flow.

Tables written:
  social_rooms        – room lifecycle (created → dissolved)
  social_room_members – per-agent join/leave history
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import SocialRoom, SocialRoomMember
from app.social_registry import ChatRoom

logger = logging.getLogger(__name__)


async def create_room_record(
    session_factory: async_sessionmaker[AsyncSession],
    room: ChatRoom,
) -> None:
    """Insert the room row and the creator's membership row."""
    try:
        async with session_factory() as session:
            session.add(SocialRoom(
                room_id=room.room_id,
                name=room.name,
                topic=room.topic or None,
                rules=room.rules or None,
                creator_agent_id=room.creator_id,
                creator_agent_name=room.creator_name,
                max_members=room.max_members,
                ttl_minutes=room.ttl_minutes,
                created_at=room.created_at,
                expires_at=room.expires_at,
            ))
            # Creator is the first member
            session.add(SocialRoomMember(
                room_id=room.room_id,
                agent_id=room.creator_id,
                agent_name=room.creator_name,
                joined_at=room.created_at,
            ))
            await session.commit()
    except Exception:
        logger.exception("social_db: failed to create room record room_id=%s", room.room_id)


async def record_member_join(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    agent_id: str,
    agent_name: str,
    joined_at: datetime,
) -> None:
    """Insert a membership row for a newly joined agent."""
    try:
        async with session_factory() as session:
            session.add(SocialRoomMember(
                room_id=room_id,
                agent_id=agent_id,
                agent_name=agent_name,
                joined_at=joined_at,
            ))
            await session.commit()
    except Exception:
        logger.exception(
            "social_db: failed to record member join room_id=%s agent_id=%s",
            room_id, agent_id,
        )


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
            # Update the latest open row (left_at IS NULL) for this agent in this room
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


async def record_room_dissolved(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    reason: str,
    total_messages: int,
    dissolved_at: Optional[datetime] = None,
    member_ids: Optional[list[str]] = None,
) -> None:
    """
    Mark the room as dissolved and close any still-open membership rows.

    member_ids: agent_ids that should have their left_at set (members who were
    still in the room at dissolution time — relevant for TTL expiry where agents
    didn't send an explicit leave_room).
    """
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
