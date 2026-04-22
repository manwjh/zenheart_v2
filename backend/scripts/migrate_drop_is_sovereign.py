#!/usr/bin/env python3
"""
Migration: drop `is_sovereign` column from agents table.

Background: the sovereign/admin agent is now identified solely by level == 0.
The is_sovereign boolean flag was redundant and has been replaced by a Python
property on the Agent model (agent.is_sovereign → agent.level == 0).

Safe to run multiple times (skips if column already absent).

Usage (from v2/backend/):
    python3 scripts/migrate_drop_is_sovereign.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import load_settings

CHECK_SQL = """
SELECT column_name FROM information_schema.columns
WHERE table_name = 'agents' AND column_name = 'is_sovereign'
"""

DROP_SQL = "ALTER TABLE agents DROP COLUMN is_sovereign"


async def main() -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(CHECK_SQL))
            exists = result.fetchone() is not None
            if not exists:
                print("Column 'is_sovereign' does not exist in agents — nothing to do.")
            else:
                await conn.execute(text(DROP_SQL))
                print("Dropped column 'is_sovereign' from agents.")
                print("Sovereign agent is now identified by level == 0.")
    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL and that Postgres is running).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
