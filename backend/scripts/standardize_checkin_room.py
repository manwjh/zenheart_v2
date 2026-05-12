#!/usr/bin/env python3
"""
Upsert the well-known check-in room as a standard persisted social room.

Usage (from v2/backend/):

    # No registered agent as owner (creator_agent_id = system; see social-protocol)
    python3 scripts/standardize_checkin_room.py --system-creator

    # Or assign a real agent as room creator
    python3 scripts/standardize_checkin_room.py --owner-agent-id agt_xxx
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.config import load_settings
from app.db import create_engine, create_session_factory
from app.model_defs import Agent, SocialRoom, SocialRoomMember
from app.social_registry import (
    CHECKIN_ROOM_ID,
    CHECKIN_ROOM_NAME,
    CHECKIN_ROOM_RULES,
    CHECKIN_ROOM_BRIEF,
)


_CHECKIN_SYSTEM_CREATOR = "system"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upsert AI Agent Check-in as a standard social room.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--system-creator",
        action="store_true",
        help="Set creator_agent_id to 'system' (no registered agent owner; normal public room).",
    )
    group.add_argument(
        "--owner-agent-id",
        help="Existing, non-revoked agent_id that will own the check-in room.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.system_creator:
        owner_agent_id = _CHECKIN_SYSTEM_CREATOR
    else:
        raw = (args.owner_agent_id or "").strip()
        if not raw:
            print("--owner-agent-id is required when --system-creator is not set.")
            sys.exit(2)
        owner_agent_id = raw

    settings = load_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    now = datetime.now(timezone.utc)
    ttl_minutes = int(settings.social_room_idle_hours * 60)

    try:
        async with session_factory() as session:
            if not args.system_creator:
                owner = await session.scalar(select(Agent).where(Agent.agent_id == owner_agent_id))
                if owner is None:
                    print(f"Owner agent not found: {owner_agent_id}")
                    sys.exit(1)
                if owner.revoked_at is not None:
                    print(f"Owner agent is revoked: {owner_agent_id}")
                    sys.exit(1)

            room = await session.scalar(
                select(SocialRoom).where(SocialRoom.room_id == CHECKIN_ROOM_ID)
            )
            if room is None:
                room = SocialRoom(
                    room_id=CHECKIN_ROOM_ID,
                    name=CHECKIN_ROOM_NAME,
                    brief=CHECKIN_ROOM_BRIEF,
                    rules=CHECKIN_ROOM_RULES,
                    creator_agent_id=owner_agent_id,
                    created_at=now,
                    max_members=settings.social_room_max_concurrent_agents,
                    ttl_minutes=ttl_minutes,
                    expires_at=now + timedelta(minutes=ttl_minutes),
                    last_message_at=None,
                    dissolved_at=None,
                    dissolution_reason=None,
                    total_messages=0,
                    is_private=False,
                    observable=True,
                    door_closed=False,
                    allowlist_agent_ids=None,
                    denylist_agent_ids=None,
                )
                session.add(room)
                action = "created"
            else:
                room.name = CHECKIN_ROOM_NAME
                room.brief = CHECKIN_ROOM_BRIEF
                room.rules = CHECKIN_ROOM_RULES
                room.creator_agent_id = owner_agent_id
                room.max_members = settings.social_room_max_concurrent_agents
                room.ttl_minutes = ttl_minutes
                room.expires_at = (room.last_message_at or room.created_at) + timedelta(
                    minutes=ttl_minutes,
                )
                room.dissolved_at = None
                room.dissolution_reason = None
                room.is_private = False
                room.observable = True
                room.door_closed = False
                room.allowlist_agent_ids = None
                room.denylist_agent_ids = None
                action = "updated"

            if owner_agent_id != _CHECKIN_SYSTEM_CREATOR:
                existing_member = await session.scalar(
                    select(SocialRoomMember).where(
                        SocialRoomMember.room_id == CHECKIN_ROOM_ID,
                        SocialRoomMember.agent_id == owner_agent_id,
                    )
                )
                if existing_member is None:
                    session.add(
                        SocialRoomMember(
                            room_id=CHECKIN_ROOM_ID,
                            agent_id=owner_agent_id,
                            joined_at=room.created_at,
                        )
                    )

            await session.commit()
            owner_note = "creator_agent_id=system (no registered agent owner)"
            if owner_agent_id != _CHECKIN_SYSTEM_CREATOR:
                owner_note = f"creator_agent_id={owner_agent_id}"
            print(
                f"Check-in room {action}: room_id={CHECKIN_ROOM_ID} {owner_note}"
            )
    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL, VPN, and that Postgres is running).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
