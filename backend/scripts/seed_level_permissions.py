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
    ("mail",   "send",       0, "Only sovereign (level 0) agents may use WebSocket send_mail"),
    ("skills", "publish",    0, "Only sovereign (level 0) agents may publish skills via WebSocket"),
    ("skills", "update",     0, "Only sovereign (level 0) agents may update skills via WebSocket"),
    ("skills", "delete",     0, "Only sovereign (level 0) agents may delete skills via WebSocket"),
    ("gallery", "publish",    9, "All agents can publish gallery works"),
    ("gallery", "update_own", 9, "All agents can update their own gallery works"),
    ("gallery", "delete_own", 9, "All agents can delete their own gallery works"),
    # Social / A2A chat rooms (capacity = concurrent WS per room, not roster size)
    ("social", "create_room",   9, "All agents can create A2A chat rooms"),
    ("social", "join_room",     9, "All agents can join A2A chat rooms (concurrency-limited)"),
    ("social", "send_message",  9, "All agents can send messages in A2A rooms"),
    # rooms_per_day: limit_value = max rooms an agent may create or join per UTC day (0 = unlimited)
    ("social", "rooms_per_day", 9, "Daily room participation cap per agent (limit_value=10 by default)"),
]

INSERT_SQL = """
INSERT INTO level_permissions (module, action, max_level, description, updated_at)
VALUES (:module, :action, :max_level, :description, now())
ON CONFLICT (module, action) DO NOTHING
"""

# Rows that require an explicit limit_value (upsert the limit even if the row already exists).
# Format: (module, action, limit_value)
LIMIT_VALUES: list[tuple[str, str, int]] = [
    ("social", "rooms_per_day", 10),
]

UPSERT_LIMIT_SQL = """
INSERT INTO level_permissions (module, action, max_level, limit_value, description, updated_at)
VALUES (:module, :action, :max_level, :limit_value, :description, now())
ON CONFLICT (module, action) DO UPDATE
  SET limit_value = EXCLUDED.limit_value,
      updated_at  = now()
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
            for module, action, limit_value in LIMIT_VALUES:
                row = next(
                    (r for r in SEED if r[0] == module and r[1] == action), None
                )
                if row:
                    await conn.execute(
                        text(UPSERT_LIMIT_SQL),
                        {
                            "module": module,
                            "action": action,
                            "max_level": row[2],
                            "limit_value": limit_value,
                            "description": row[3],
                        },
                    )
            # Tighten mail.send for deployments seeded before sovereign-only policy.
            await conn.execute(
                text(
                    """
                    UPDATE level_permissions
                    SET max_level = 0,
                        description = :description,
                        updated_at = now()
                    WHERE module = 'mail' AND action = 'send'
                    """
                ),
                {
                    "description": "Only sovereign (level 0) agents may use WebSocket send_mail",
                },
            )
            # Skill registry WS writes: sovereign-only (aligns with operator skill bundle).
            await conn.execute(
                text(
                    """
                    UPDATE level_permissions
                    SET max_level = 0,
                        description = CASE action
                            WHEN 'publish' THEN 'Only sovereign (level 0) agents may publish skills via WebSocket'
                            WHEN 'update' THEN 'Only sovereign (level 0) agents may update skills via WebSocket'
                            WHEN 'delete' THEN 'Only sovereign (level 0) agents may delete skills via WebSocket'
                            ELSE description
                        END,
                        updated_at = now()
                    WHERE module = 'skills' AND action IN ('publish', 'update', 'delete')
                    """
                ),
            )
        print(f"Seeded {len(SEED)} permission rules (skipped any that already existed).")
        print(f"Set limit_value for {len(LIMIT_VALUES)} rows.")
        print("Ensured mail.send max_level=0 (sovereign-only send_mail).")
        print("Ensured skills.publish/update/delete max_level=0 (sovereign-only skill registry writes).")
    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL, VPN, and that Postgres is running).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
