#!/usr/bin/env python3
"""
Migration: add article_comments table and news_articles.category column.

Safe to run multiple times (idempotent checks before each DDL statement).

Usage (from v2/backend/):
    python3 scripts/migrate_article_comments_and_category.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import load_settings

CHECK_CATEGORY = """
SELECT column_name FROM information_schema.columns
WHERE table_name = 'news_articles' AND column_name = 'category'
"""

ADD_CATEGORY = "ALTER TABLE news_articles ADD COLUMN category VARCHAR(60)"

CHECK_COMMENTS = """
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'article_comments'
"""

CREATE_COMMENTS = """
CREATE TABLE article_comments (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id          UUID         NOT NULL,
    publisher_agent_id  VARCHAR(80)  NOT NULL,
    from_type           VARCHAR(20)  NOT NULL,
    from_agent_id       VARCHAR(80),
    from_name           VARCHAR(120),
    body                TEXT         NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX ix_article_comments_article_status
    ON article_comments (article_id, status, created_at);

CREATE INDEX ix_article_comments_publisher
    ON article_comments (publisher_agent_id);
"""


async def main() -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            # 1. news_articles.category
            result = await conn.execute(text(CHECK_CATEGORY))
            if result.fetchone():
                print("Column 'category' already exists in news_articles — skipped.")
            else:
                await conn.execute(text(ADD_CATEGORY))
                print("Added column 'category' (VARCHAR(60), nullable) to news_articles.")

            # 2. article_comments table
            result = await conn.execute(text(CHECK_COMMENTS))
            if result.fetchone():
                print("Table 'article_comments' already exists — skipped.")
            else:
                await conn.execute(text(CREATE_COMMENTS))
                print("Created table 'article_comments' with indexes.")

    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL and that Postgres is running).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
