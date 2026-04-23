#!/usr/bin/env python3
"""
Migration: replace single news_articles.category with two-level categories.

Steps:
1) Add category_level1 / category_level2 columns if missing.
2) Copy legacy category -> category_level1 where empty.
3) Drop legacy category column if it exists.

Safe to run multiple times.

Usage (from v2/backend/):
    python3 scripts/migrate_news_articles_two_level_category.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import load_settings

HAS_CATEGORY_SQL = """
SELECT 1 FROM information_schema.columns
WHERE table_name = 'news_articles' AND column_name = 'category'
"""

HAS_LEVEL1_SQL = """
SELECT 1 FROM information_schema.columns
WHERE table_name = 'news_articles' AND column_name = 'category_level1'
"""

HAS_LEVEL2_SQL = """
SELECT 1 FROM information_schema.columns
WHERE table_name = 'news_articles' AND column_name = 'category_level2'
"""

ADD_LEVEL1_SQL = "ALTER TABLE news_articles ADD COLUMN category_level1 VARCHAR(60)"
ADD_LEVEL2_SQL = "ALTER TABLE news_articles ADD COLUMN category_level2 VARCHAR(60)"

COPY_LEGACY_SQL = """
UPDATE news_articles
SET category_level1 = category
WHERE category IS NOT NULL
  AND (category_level1 IS NULL OR category_level1 = '')
"""

DROP_LEGACY_SQL = "ALTER TABLE news_articles DROP COLUMN category"


async def _column_exists(conn, sql: str) -> bool:
    result = await conn.execute(text(sql))
    return result.fetchone() is not None


async def main() -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            has_level1 = await _column_exists(conn, HAS_LEVEL1_SQL)
            has_level2 = await _column_exists(conn, HAS_LEVEL2_SQL)
            has_category = await _column_exists(conn, HAS_CATEGORY_SQL)

            if not has_level1:
                await conn.execute(text(ADD_LEVEL1_SQL))
                print("Added column 'category_level1' to news_articles.")
            if not has_level2:
                await conn.execute(text(ADD_LEVEL2_SQL))
                print("Added column 'category_level2' to news_articles.")

            if has_category:
                await conn.execute(text(COPY_LEGACY_SQL))
                await conn.execute(text(DROP_LEGACY_SQL))
                print("Migrated legacy 'category' -> 'category_level1' and dropped 'category'.")
            else:
                print("Legacy column 'category' not found — nothing to migrate.")
    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL, VPN, and Postgres service).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
