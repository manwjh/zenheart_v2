"""
Async helpers for persisting A2A social room data to the database.

All functions use fire-and-forget semantics (same as agent_event_log):
exceptions are caught and logged so that a DB hiccup never breaks the
WebSocket flow.

Tables written:
  social_rooms        – room lifecycle, last_message_at, dissolved metadata
  social_room_members – per-agent join/leave history
  social_messages     – full text of each chat message (for replay on join/subscribe)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import SocialMessage, SocialRoom, SocialRoomMember
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
                created_at=room.created_at,
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
