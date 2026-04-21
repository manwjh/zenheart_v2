#!/usr/bin/env python3
"""Print news_articles columns and whether `keywords` exists. Run from repo: cd v2/backend && python3 scripts/check_news_keywords_column.py"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import load_settings


async def main() -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        try:
            async with engine.connect() as conn:
                r = await conn.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'news_articles' "
                        "ORDER BY ordinal_position"
                    )
                )
                rows = r.fetchall()
        except OSError as exc:
            print("Cannot reach PostgreSQL (check DATABASE_URL, VPN, and that Postgres is running).")
            print(f"Detail: {exc}")
            sys.exit(3)
    finally:
        await engine.dispose()

    if not rows:
        print("Table public.news_articles not found (or no columns visible).")
        sys.exit(2)

    names = [row[0] for row in rows]
    print("news_articles columns:", ", ".join(names))
    if "keywords" in names:
        idx = names.index("keywords")
        dt = rows[idx][1]
        print(f"keywords: OK (type {dt})")
        sys.exit(0)
    print("keywords: MISSING — apply v2/backend/scripts/add-news-articles-keywords.sql then retry.")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
