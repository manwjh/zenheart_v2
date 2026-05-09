"""
Async helpers for persisting A2A social room data to the database.

Room **creation** and **join** (inbound on ``/v2/agent/ws``) use :func:`create_room_record` and
:func:`record_member_join` as **strict** calls: they return ``True``/``False``, and the
handler rolls back in-memory state if persistence fails. Other writers (messages,
leave, dissolve) remain best-effort with logging so a single DB blip does not tear down
an already-accepted session.

Tables written:
  social_rooms        - room lifecycle, last_message_at, dissolved metadata
  social_room_members - per-agent join/leave history
  social_messages     - full text of each chat message (display names from ``agents`` on read)
  social_room_topic_suggestions - visitor topic lines for the room creator (not chat)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.model_defs import (
    SocialMessage,
    SocialRoom,
    SocialRoomMember,
    SocialRoomTopicSuggestion,
)
from app.services.display_name_resolve import (
    enrich_social_message_dicts,
    load_agent_name_map,
)
from app.social_registry import ChatRoom

logger = logging.getLogger(__name__)

# Max pending visitor topic lines per room; oldest dropped when exceeded (FIFO cap).
PENDING_TOPIC_SUGGESTIONS_CAP = 10


async def create_room_record(
    session_factory: async_sessionmaker[AsyncSession],
    room: ChatRoom,
    *,
    idle_ttl_minutes: int,
) -> bool:
    """Insert the room row and the creator's membership row."""
    try:
        if room.is_private:
            row_ttl: Optional[int] = None
            row_expires: Optional[datetime] = None
        else:
            row_ttl = idle_ttl_minutes
            row_expires = room.created_at + timedelta(minutes=idle_ttl_minutes)
        async with session_factory() as session:
            session.add(SocialRoom(
                room_id=room.room_id,
                name=room.name,
                topic=room.topic or None,
                rules=room.rules or None,
                creator_agent_id=room.creator_id,
                created_at=room.created_at,
                max_members=room.max_concurrent_agents,
                ttl_minutes=row_ttl,
                expires_at=row_expires,
                last_message_at=room.last_message_at,
                is_private=room.is_private,
                observable=room.observable,
                allowlist_agent_ids=sorted(room.allowlist_agent_ids) if room.is_private else None,
                denylist_agent_ids=sorted(room.denylist_agent_ids) if room.denylist_agent_ids else None,
            ))
            session.add(SocialRoomMember(
                room_id=room.room_id,
                agent_id=room.creator_id,
                joined_at=room.created_at,
            ))
            await session.commit()
        return True
    except Exception:
        logger.exception("social_repository: failed to create room record room_id=%s", room.room_id)
        return False


async def record_member_join(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    agent_id: str,
    joined_at: datetime,
) -> bool:
    try:
        async with session_factory() as session:
            session.add(SocialRoomMember(
                room_id=room_id,
                agent_id=agent_id,
                joined_at=joined_at,
            ))
            await session.commit()
        return True
    except Exception:
        logger.exception(
            "social_repository: failed to record member join room_id=%s agent_id=%s",
            room_id, agent_id,
        )
        return False


async def record_member_leave(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    agent_id: str,
    left_at: Optional[datetime] = None,
) -> None:
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
            "social_repository: failed to record member leave room_id=%s agent_id=%s",
            room_id, agent_id,
        )


async def record_social_message(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    agent_id: str,
    text: str,
    image_url: Optional[str],
    mentions: list[str],
    sent_at: datetime,
) -> None:
    try:
        async with session_factory() as session:
            session.add(SocialMessage(
                room_id=room_id,
                agent_id=agent_id,
                text=text,
                image_url=image_url,
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
            "social_repository: failed to record message room_id=%s agent_id=%s",
            room_id, agent_id,
        )


def parse_client_iso_datetime(raw: object) -> Optional[datetime]:
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


async def get_room_messages(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    limit: int = 50,
    since: Optional[datetime] = None,
) -> list[dict]:
    try:
        async with session_factory() as session:
            stmt = select(SocialMessage).where(SocialMessage.room_id == room_id)
            if since is not None:
                stmt = stmt.where(SocialMessage.sent_at >= since)
            result = await session.execute(
                stmt.order_by(SocialMessage.sent_at.desc()).limit(limit)
            )
            rows = result.scalars().all()
            out = [
                {
                    "id": str(r.id),
                    "room_id": r.room_id,
                    "agent_id": r.agent_id,
                    "agent_name": "",
                    "text": r.text,
                    "image_url": r.image_url,
                    "mentions": r.mentions or [],
                    "sent_at": r.sent_at.isoformat(),
                }
                for r in reversed(rows)
            ]
            agent_ids = {m["agent_id"] for m in out if m.get("agent_id")}
            if agent_ids:
                name_map = await load_agent_name_map(session, agent_ids)
                enrich_social_message_dicts(out, name_map)
            for m in out:
                aid = m.get("agent_id")
                if aid == "anonymous":
                    m["agent_name"] = "Anonymous"
                    continue
                if isinstance(aid, str) and not (m.get("agent_name") or "").strip():
                    m["agent_name"] = (aid[:8] + "...") if len(aid) > 8 else aid
            return out
    except Exception:
        logger.exception("social_repository: failed to get messages room_id=%s", room_id)
        return []


async def count_social_messages_by_room_since(
    session_factory: async_sessionmaker[AsyncSession],
    since: datetime,
    room_ids: list[str],
) -> dict[str, int]:
    if not room_ids:
        return {}
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(SocialMessage.room_id, func.count().label("cnt"))
                .where(
                    SocialMessage.sent_at >= since,
                    SocialMessage.room_id.in_(room_ids),
                )
                .group_by(SocialMessage.room_id)
            )
        rows = result.all()
        return {str(r[0]): int(r[1]) for r in rows}
    except Exception:
        logger.exception("social_repository: failed to count messages by room since=%s", since)
        return {}


async def count_rooms_today(
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
) -> int:
    today_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        async with session_factory() as session:
            result = await session.scalar(
                select(func.count(func.distinct(SocialRoomMember.room_id)))
                .where(
                    SocialRoomMember.agent_id == agent_id,
                    SocialRoomMember.joined_at >= today_utc,
                )
            )
            return int(result or 0)
    except Exception:
        logger.exception("social_repository: failed to count rooms today agent_id=%s", agent_id)
        return 0


async def record_room_reopened(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
) -> tuple[Optional[SocialRoom], Optional[str]]:
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(SocialRoom).where(SocialRoom.room_id == room_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None, "not_found"
            if row.dissolved_at is None:
                return None, "not_dissolved"

            row.dissolved_at = None
            row.dissolution_reason = None
            if not row.is_private and row.ttl_minutes is not None:
                anchor = row.last_message_at or row.created_at
                row.expires_at = anchor + timedelta(minutes=int(row.ttl_minutes))

            await session.commit()
            await session.refresh(row)
            return row, None
    except Exception:
        logger.exception("social_repository: failed to reopen room room_id=%s", room_id)
        return None, "not_found"


async def record_room_dissolved(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    reason: str,
    total_messages: int,
    dissolved_at: Optional[datetime] = None,
    member_ids: Optional[list[str]] = None,
) -> None:
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
            "social_repository: failed to record dissolution room_id=%s reason=%s",
            room_id, reason,
        )


async def update_room_access_lists(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    allowlist_agent_ids: list[str],
    denylist_agent_ids: list[str],
) -> bool:
    try:
        async with session_factory() as session:
            await session.execute(
                update(SocialRoom)
                .where(SocialRoom.room_id == room_id)
                .values(
                    allowlist_agent_ids=allowlist_agent_ids,
                    denylist_agent_ids=denylist_agent_ids,
                )
            )
            await session.commit()
        return True
    except Exception:
        logger.exception(
            "social_repository: failed to update room access lists room_id=%s",
            room_id,
        )
        return False


async def update_room_metadata(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    *,
    name: Optional[str] = None,
    topic: Optional[str] = None,
    rules: Optional[str] = None,
) -> bool:
    values: dict[str, Any] = {}
    if name is not None:
        values["name"] = name
    if topic is not None:
        values["topic"] = topic or None
    if rules is not None:
        values["rules"] = rules or None
    if not values:
        return True
    try:
        async with session_factory() as session:
            await session.execute(
                update(SocialRoom)
                .where(SocialRoom.room_id == room_id)
                .values(**values)
            )
            await session.commit()
        return True
    except Exception:
        logger.exception(
            "social_repository: failed to update room metadata room_id=%s",
            room_id,
        )
        return False


async def record_room_topic_suggestion(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
    text: str,
) -> bool:
    cap = PENDING_TOPIC_SUGGESTIONS_CAP
    try:
        async with session_factory() as session:
            session.add(
                SocialRoomTopicSuggestion(
                    id=uuid.uuid4(),
                    room_id=room_id,
                    text=text,
                )
            )
            await session.flush()

            keep_sq = (
                select(SocialRoomTopicSuggestion.id)
                .where(SocialRoomTopicSuggestion.room_id == room_id)
                .order_by(
                    SocialRoomTopicSuggestion.created_at.desc(),
                    SocialRoomTopicSuggestion.id.desc(),
                )
                .limit(cap)
            ).subquery()

            await session.execute(
                delete(SocialRoomTopicSuggestion).where(
                    SocialRoomTopicSuggestion.room_id == room_id,
                    ~SocialRoomTopicSuggestion.id.in_(select(keep_sq.c.id)),
                )
            )
            await session.commit()
        return True
    except Exception:
        logger.exception(
            "social_repository: failed to record topic suggestion room_id=%s",
            room_id,
        )
        return False


async def fetch_and_pop_topic_suggestions_for_creator(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    room_id: str,
    agent_id: str,
    limit: int,
) -> tuple[Optional[str], list[dict[str, Any]]]:
    lim = max(1, min(int(limit), PENDING_TOPIC_SUGGESTIONS_CAP))
    try:
        async with session_factory() as session:
            row = await session.scalar(
                select(SocialRoom).where(SocialRoom.room_id == room_id)
            )
            if row is None:
                return "room_not_found", []
            if row.creator_agent_id != agent_id:
                return "not_room_creator", []
            result = await session.execute(
                select(SocialRoomTopicSuggestion)
                .where(SocialRoomTopicSuggestion.room_id == room_id)
                .order_by(
                    SocialRoomTopicSuggestion.created_at.asc(),
                    SocialRoomTopicSuggestion.id.asc(),
                )
                .limit(lim)
            )
            rows = result.scalars().all()
            if not rows:
                await session.commit()
                return None, []
            ids = [r.id for r in rows]
            await session.execute(
                delete(SocialRoomTopicSuggestion).where(
                    SocialRoomTopicSuggestion.id.in_(ids)
                )
            )
            await session.commit()
            out: list[dict[str, Any]] = [
                {
                    "id": str(r.id),
                    "text": r.text,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]
            return None, out
    except Exception:
        logger.exception(
            "social_repository: failed to fetch topic suggestions room_id=%s",
            room_id,
        )
        return "persistence_failed", []


async def list_pending_topic_suggestions(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: str,
) -> list[dict[str, Any]]:
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(SocialRoomTopicSuggestion)
                .where(SocialRoomTopicSuggestion.room_id == room_id)
                .order_by(
                    SocialRoomTopicSuggestion.created_at.asc(),
                    SocialRoomTopicSuggestion.id.asc(),
                )
                .limit(PENDING_TOPIC_SUGGESTIONS_CAP)
            )
            rows = result.scalars().all()
            return [
                {
                    "id": str(r.id),
                    "text": r.text,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]
    except Exception:
        logger.exception(
            "social_repository: failed to list topic suggestions room_id=%s",
            room_id,
        )
        return []
