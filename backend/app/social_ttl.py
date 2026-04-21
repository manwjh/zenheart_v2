"""
Background idle enforcer for A2A chat rooms.

Runs as a persistent asyncio task. Every 30 seconds it:
  1. Dissolves rooms whose idle anchor (last message time, else creation time)
     is older than the configured idle interval (idle_timeout).
  2. Ensures the permanent check-in room exists (recreates it if missing).
"""
from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.services.agent_event_log import record_agent_event
from app.services.social_db import record_room_dissolved
from app.services.social_notify import build_room_dissolved_notify, schedule_social_notify
from app.social_registry import SocialRoomRegistry
from app.ws_registry import AgentConnectionRegistry

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 30


async def run_social_ttl_enforcer(
    social: SocialRoomRegistry,
    session_factory: object,
    registry: AgentConnectionRegistry,
    settings: Settings,
) -> None:
    """Run forever. Cancel to stop (e.g. during lifespan shutdown)."""
    while True:
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
        try:
            dissolved_rooms = await social.dissolve_expired()
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
                        "total_messages": room.message_count,
                    },
                )
                logger.info(
                    "A2A room dissolved: %s (%s) reason=%s",
                    room.room_id, room.name, reason,
                )
                if member_ids:
                    ws_body, hook_payload = build_room_dissolved_notify(
                        room_id=room.room_id,
                        room_name=room.name,
                        reason=reason,
                    )
                    schedule_social_notify(
                        session_factory=session_factory,
                        registry=registry,
                        settings=settings,
                        recipient_agent_ids=member_ids,
                        ws_body=ws_body,
                        webhook_event="social.room_dissolved",
                        webhook_payload=hook_payload,
                    )

            await social.ensure_checkin_room()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in social TTL enforcer")
