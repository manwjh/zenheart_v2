"""
Background TTL enforcer for A2A chat rooms.

Runs as a persistent asyncio task. Every 30 seconds it:
  1. Dissolves rooms whose expires_at has passed (ttl_expired).
  2. Dissolves rooms that have been empty for >= ROOM_KEEPALIVE_MINUTES (all_members_left).
  3. Ensures the permanent check-in room exists (recreates it if missing).
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
            dissolved_rooms = await social.dissolve_expired()
            # dissolve_expired removes rooms from the registry under the lock and
            # returns snapshots. Any concurrent leave_room call that wins the lock
            # first will find the room already gone and return (None, False), leaving
            # left_at as NULL in social_room_members — an accepted trade-off noted in
            # the model comment ("NULL means still in room or abnormal exit").
            for room, reason in dissolved_rooms:
                member_ids = list(room.members.keys())
                await social.broadcast_dissolution(room, reason=reason)
                await record_room_dissolved(
                    session_factory,
                    room_id=room.room_id,
                    reason=reason,
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
                        "reason": reason,
                        "ttl_minutes": room.ttl_minutes,
                        "total_messages": room.message_count,
                    },
                )
                logger.info(
                    "A2A room dissolved: %s (%s) reason=%s",
                    room.room_id, room.name, reason,
                )

            await social.ensure_checkin_room()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in social TTL enforcer")
