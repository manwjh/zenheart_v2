#!/usr/bin/env python3
"""
Migration: shrink news_articles.title from VARCHAR(300) to VARCHAR(200).

Refuses to run if any row has char_length(title) > 200 (manual trim required first).

Usage (from v2/backend/):
    python3 scripts/migrate_news_articles_title_varchar_200.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import load_settings

LONG_SQL = """
SELECT id::text, char_length(title) AS n
FROM news_articles
WHERE char_length(title) > 200
ORDER BY n DESC
LIMIT 20
"""

TYPE_SQL = """
SELECT data_type, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'news_articles' AND column_name = 'title'
"""

ALTER_SQL = "ALTER TABLE news_articles ALTER COLUMN title TYPE VARCHAR(200)"


async def main() -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            r = await conn.execute(text(LONG_SQL))
            bad = r.fetchall()
            if bad:
                print("Refusing migration: at least one title is longer than 200 characters.")
                for row in bad:
                    print(f"  id={row[0]} length={row[1]}")
                print("Shorten or split those titles, then re-run.")
                sys.exit(1)

            r2 = await conn.execute(text(TYPE_SQL))
            info = r2.fetchone()
            if not info:
                print("Column news_articles.title not found — check schema.")
                sys.exit(1)
            dtype, cmax = info[0], info[1]
            if dtype not in ("character varying", "varchar"):
                print(f"Unexpected title column type: {dtype!r} len={cmax!r}")
                sys.exit(1)
            if cmax == 200:
                print("Column title is already VARCHAR(200) — nothing to do.")
                return

            await conn.execute(text(ALTER_SQL))
            print("Altered news_articles.title to VARCHAR(200).")
    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL, VPN, and that Postgres is running).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
