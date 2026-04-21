#!/usr/bin/env python3
"""Run SQL files in a directory against DATABASE_URL (PostgreSQL). No psql required."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg


def _postgres_dsn(database_url: str) -> str:
    url = database_url.strip()
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://") :]
    if url.startswith("postgres+asyncpg://"):
        return "postgres://" + url[len("postgres+asyncpg://") :]
    return url


async def _main(migrations_dir: Path) -> None:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    if "sqlite" in raw.split(":", 1)[0].lower():
        print("skip: migrations are PostgreSQL-only (sqlite URL)", file=sys.stderr)
        return

    dsn = _postgres_dsn(raw)
    sql_files = sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())
    if not sql_files:
        return

    conn = await asyncpg.connect(dsn)
    try:
        for path in sql_files:
            sql = path.read_text(encoding="utf-8").strip()
            if not sql:
                continue
            await conn.execute(sql)
            print(f"ok: {path.name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <migrations_dir>", file=sys.stderr)
        sys.exit(2)
    asyncio.run(_main(Path(sys.argv[1]).resolve()))
