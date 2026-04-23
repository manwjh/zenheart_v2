#!/usr/bin/env python3
"""
Migration: add `score` column to news_articles table.
Safe to run multiple times (checks information_schema first).

Usage (from v2/backend/):
    python3 scripts/migrate_news_articles_score.py
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
WHERE table_name = 'news_articles' AND column_name = 'score'
"""

ALTER_SQL = "ALTER TABLE news_articles ADD COLUMN score INTEGER NOT NULL DEFAULT 0"


async def main() -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(CHECK_SQL))
            exists = result.fetchone() is not None
            if exists:
                print("Column 'score' already exists in news_articles — nothing to do.")
            else:
                await conn.execute(text(ALTER_SQL))
                print("Added column 'score' (INTEGER NOT NULL DEFAULT 0) to news_articles.")
    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL, VPN, and that Postgres is running).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
