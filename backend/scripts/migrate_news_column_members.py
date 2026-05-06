#!/usr/bin/env python3
"""
Create `news_column_members` for admin-managed featured news columns.
Safe to run multiple times (CREATE TABLE IF NOT EXISTS).

Production: this schema is applied automatically by `scripts/run_migrations.py` when
`deploy-backend.sh` runs (see `scripts/migrations/011_news_column_members.sql`).

Ad-hoc / local (from v2/backend/):
    python3 scripts/migrate_news_column_members.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import load_settings

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS news_column_members (
    agent_id VARCHAR(80) NOT NULL PRIMARY KEY,
    sort_order INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_news_column_members_sort_order ON news_column_members (sort_order)"
)


async def main() -> None:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(CREATE_TABLE_SQL))
            await conn.execute(text(CREATE_INDEX_SQL))
        print("Ensured table news_column_members + index ix_news_column_members_sort_order exist.")
    except OSError as exc:
        print("Cannot reach PostgreSQL (check DATABASE_URL, VPN, and that Postgres is running).")
        print(f"Detail: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
