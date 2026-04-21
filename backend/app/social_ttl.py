"""
Background TTL enforcer for A2A chat rooms.

Runs as a persistent asyncio task. Every 30 seconds it scans for rooms
whose expires_at has passed, dissolves them, notifies all members and
observers, and logs the event.
"""
from __future__ import annotations

import asyncio
import logging

from app.services.agent_event_log import record_agent_event
from app.services.social_db import record_room_dissolved
from app.social_registry import SocialRoomRegistry

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 30


async def run_social_ttl_enforcer(
    social: SocialRoomRegistry,
    session_factory: object,
) -> None:
    """Run forever. Cancel to stop (e.g. during lifespan shutdown)."""
    while True:
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
        try:
            expired_rooms = await social.dissolve_expired()
            for room in expired_rooms:
                member_ids = list(room.members.keys())
                await social.broadcast_dissolution(room, reason="ttl_expired")
                await record_room_dissolved(
                    session_factory,
                    room_id=room.room_id,
                    reason="ttl_expired",
                    total_messages=room.message_count,
                    member_ids=member_ids,
                )
                await record_agent_event(
                    session_factory,
                    event="a2a_room_dissolved",
                    agent_id=room.creator_id,
                    detail={
                        "room_id": room.room_id,
                        "name": room.name,
                        "reason": "ttl_expired",
                        "ttl_minutes": room.ttl_minutes,
                        "total_messages": room.message_count,
                    },
                )
                logger.info("A2A room dissolved by TTL: %s (%s)", room.room_id, room.name)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in social TTL enforcer")
