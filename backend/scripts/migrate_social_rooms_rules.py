#!/usr/bin/env python3
"""
Migration: add `rules` column to social_rooms table.
Safe to run multiple times (uses IF NOT EXISTS check).

Usage (from v2/backend/):
    python3 scripts/migrate_social_rooms_rules.py
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
WHERE table_name = 'social_rooms' AND column_name = 'rules'
"""

ALTER_SQL = "ALTER TABLE social_rooms ADD COLUMN rules TEXT"


async def main() -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(CHECK_SQL))
            exists = result.fetchone() is not None
            if exists:
                print("Column 'rules' already exists in social_rooms — nothing to do.")
            else:
                await conn.execute(text(ALTER_SQL))
                print("Added column 'rules' (TEXT, nullable) to social_rooms.")
    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL, VPN, and that Postgres is running).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
