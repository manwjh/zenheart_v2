#!/usr/bin/env python3
"""Run SQL files in a directory against DATABASE_URL (PostgreSQL). No psql required."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

# Per-statement and connection-close cap (deploy SSH is non-TTY; close can hang on SSL teardown).
_DEFAULT_COMMAND_TIMEOUT = 300.0
_CONNECT_TIMEOUT = 60.0
_CLOSE_TIMEOUT = 8.0
_EXECUTE_TIMEOUT = 600.0  # max seconds per single migration file


def _postgres_dsn(database_url: str) -> str:
    url = database_url.strip()
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://") :]
    if url.startswith("postgres+asyncpg://"):
        return "postgres://" + url[len("postgres+asyncpg://") :]
    return url


def _p(msg: str) -> None:
    print(msg, flush=True)


async def _main(migrations_dir: Path) -> None:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        _p("error: DATABASE_URL is not set")
        sys.exit(1)
    if "sqlite" in raw.split(":", 1)[0].lower():
        _p("skip: migrations are PostgreSQL-only (sqlite URL)")
        return

    dsn = _postgres_dsn(raw)
    sql_files = sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())
    if not sql_files:
        _p("ok: no .sql files in migrations dir")
        return

    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(
                dsn,
                timeout=_CONNECT_TIMEOUT,
                command_timeout=_DEFAULT_COMMAND_TIMEOUT,
            ),
            timeout=_CONNECT_TIMEOUT + 5.0,
        )
    except (asyncio.TimeoutError, OSError) as e:
        _p(f"error: could not connect to database: {e}")
        sys.exit(1)

    try:
        for path in sql_files:
            sql = path.read_text(encoding="utf-8").strip()
            if not sql:
                continue
            try:
                await asyncio.wait_for(conn.execute(sql), timeout=_EXECUTE_TIMEOUT)
            except asyncio.TimeoutError:
                _p(f"error: migration timed out after {_EXECUTE_TIMEOUT}s: {path.name}")
                sys.exit(1)
            _p(f"ok: {path.name}")
        _p("ok: migrations complete (closing connection)")
    finally:
        if conn is not None:
            try:
                await asyncio.wait_for(conn.close(), timeout=_CLOSE_TIMEOUT)
            except (asyncio.TimeoutError, Exception):
                try:
                    conn.terminate()
                except Exception:
                    pass
            _p("ok: database connection closed")


def _run_safely(coro) -> None:
    """
    Run the coroutine and tear down the loop without hanging on asyncpg/SSL async shutdown.
    (asyncio.run can occasionally block in loop.close on rare executor/thread edge cases over SSH.)
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro)
    finally:
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=5.0,
                    )
                )
        except (asyncio.TimeoutError, Exception):
            pass
        try:
            loop.close()
        except Exception:
            pass
        asyncio.set_event_loop(None)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <migrations_dir>", file=sys.stderr)
        sys.exit(2)
    _run_safely(_main(Path(sys.argv[1]).resolve()))
    _p("ok: run_migrations.py exiting")
