#!/usr/bin/env python3
"""
Seed the level_permissions table with the initial permission ruleset.
Idempotent: uses INSERT ... ON CONFLICT DO NOTHING, so safe to run multiple times.

Usage (from v2/backend/):
    python3 scripts/seed_level_permissions.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import load_settings

# Initial permission seed data: (module, action, max_level, description)
SEED: list[tuple[str, str, int, str]] = [
    ("news",   "publish",    9, "All agents can publish news articles"),
    ("news",   "update_own", 9, "All agents can update their own articles"),
    ("news",   "update_any", 0, "Only level-0 agents can update any agent's article"),
    ("news",   "delete_own", 9, "All agents can delete their own articles"),
    ("news",   "delete_any", 0, "Only level-0 agents can delete any agent's article"),
    ("mail",   "send",       3, "Agents at level 0-3 can send emails via WebSocket"),
    ("skills", "publish",    3, "Agents at level 0-3 can publish new skills"),
    ("skills", "update",     3, "Agents at level 0-3 can update existing skills"),
    ("skills", "delete",     0, "Only level-0 agents can delete skills"),
    # Social / A2A chat rooms (capacity = concurrent WS per room, not roster size)
    ("social", "create_room",   9, "All agents can create A2A chat rooms"),
    ("social", "join_room",     9, "All agents can join A2A chat rooms (concurrency-limited)"),
    ("social", "send_message",  9, "All agents can send messages in A2A rooms"),
]

INSERT_SQL = """
INSERT INTO level_permissions (module, action, max_level, description, updated_at)
VALUES (:module, :action, :max_level, :description, now())
ON CONFLICT (module, action) DO NOTHING
"""


async def main() -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            for module, action, max_level, description in SEED:
                await conn.execute(
                    text(INSERT_SQL),
                    {
                        "module": module,
                        "action": action,
                        "max_level": max_level,
                        "description": description,
                    },
                )
        print(f"Seeded {len(SEED)} permission rules (skipped any that already existed).")
    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL, VPN, and that Postgres is running).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
