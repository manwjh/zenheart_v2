#!/usr/bin/env python3
"""Align on-disk media filenames with sniffed image types; update DB URL columns.

Scans MEDIA_ROOT/images, compares each file's magic bytes to its extension
(via sniff_image_content_type in this script; keep in sync with app.services.image_check).
When they disagree, copies to the correct name, updates known text columns that may hold
/media/images/... URLs, removes the old file.

Usage:
  cd v2/backend && .venv/bin/python scripts/repair_media_extensions.py -e .env
  .venv/bin/python scripts/repair_media_extensions.py -e .env --apply

Requires DATABASE_URL and MEDIA_ROOT (from environment or --env-file / -e).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sys
import traceback
from pathlib import Path

import asyncpg


def sniff_image_content_type(data: bytes) -> str | None:
    """Keep in sync with app.services.image_check.sniff_image_content_type."""
    if not data:
        return None
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    text_head = data[:4096].decode("utf-8", errors="ignore").lstrip("\ufeff \t\r\n")
    lowered = text_head[:512].lower()
    if lowered.startswith("<?xml") or lowered.startswith("<svg") or "<svg" in lowered or lowered.startswith(
        "<!doctype svg"
    ):
        return "image/svg+xml"
    return None


_CT_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}

_ALLOWED_SUFFIXES = frozenset(_CT_EXT.values())

# (table, column) pairs that may store /media/images/<file> paths (relative or in full URL).
REF_COLUMNS: tuple[tuple[str, str], ...] = (
    ("social_messages", "image_url"),
    ("news_articles", "cover_image_url"),
    ("agent_gallery_works", "image_url"),
)

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _load_env_file(path: Path) -> None:
    raw = path.read_text(encoding="utf-8", errors="strict")
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _ENV_LINE.match(s)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ[key] = val


def _asyncpg_dsn(database_url: str) -> str:
    u = database_url.strip().strip('"').strip("'")
    return u.replace("postgresql+asyncpg://", "postgresql://", 1)


def _wanted_suffix(data: bytes) -> str | None:
    ct = sniff_image_content_type(data)
    if ct is None or ct not in _CT_EXT:
        return None
    return _CT_EXT[ct]


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    row = await conn.fetchrow(
        "SELECT to_regclass($1) IS NOT NULL AS ok",
        f"public.{table}",
    )
    return bool(row and row["ok"])


async def _ref_tables_present(conn: asyncpg.Connection) -> set[str]:
    present: set[str] = set()
    for table, _col in REF_COLUMNS:
        if await _table_exists(conn, table):
            present.add(table)
    return present


async def _count_refs(
    conn: asyncpg.Connection,
    old_fragment: str,
    *,
    tables: set[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, col in REF_COLUMNS:
        if table not in tables:
            continue
        n = await conn.fetchval(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NOT NULL AND "{col}" LIKE $1',
            f"%{old_fragment}%",
        )
        counts[f"{table}.{col}"] = int(n or 0)
    return counts


async def _apply_updates(
    conn: asyncpg.Connection,
    old_fragment: str,
    new_fragment: str,
    *,
    tables: set[str],
) -> int:
    total = 0
    for table, col in REF_COLUMNS:
        if table not in tables:
            continue
        status: str = await conn.execute(
            f'UPDATE "{table}" SET "{col}" = REPLACE("{col}", $1, $2) '
            f'WHERE "{col}" IS NOT NULL AND "{col}" LIKE $3',
            old_fragment,
            new_fragment,
            f"%{old_fragment}%",
        )
        parts = status.split()
        if len(parts) >= 2 and parts[0] == "UPDATE":
            total += int(parts[1])
    return total


async def _run(
    *,
    media_root: Path,
    apply: bool,
) -> int:
    media_root = media_root.resolve()
    images_dir = (media_root / "images").resolve()
    if not images_dir.is_dir():
        print(f"error: not a directory: {images_dir}", file=sys.stderr)
        return 1

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("error: DATABASE_URL is not set (use env or --env-file)", file=sys.stderr)
        return 1

    dsn = _asyncpg_dsn(db_url)
    conn = await asyncpg.connect(dsn)
    tables = await _ref_tables_present(conn)

    mismatches: list[tuple[Path, str, str]] = []
    unrecognized: list[Path] = []
    matched = 0

    for path in sorted(images_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            continue
        data = path.read_bytes()[:65536]
        want = _wanted_suffix(data)
        if want is None:
            unrecognized.append(path)
            continue
        if suffix == want:
            matched += 1
            continue
        mismatches.append((path, suffix, want))

    print(f"scan: {images_dir}")
    print(f"extension matches sniff: {matched}")
    print(f"mismatch (will repair): {len(mismatches)}")
    print(f"unrecognized magic: {len(unrecognized)}")
    for p in unrecognized:
        print(f"  SKIP unrecognized: {p.name}")

    exit_code = 0
    for path, got_ext, want_ext in mismatches:
        old_name = path.name
        stem = path.stem
        new_name = f"{stem}{want_ext}"
        old_fragment = f"/media/images/{old_name}"
        new_fragment = f"/media/images/{new_name}"
        new_path = path.with_name(new_name)

        counts = await _count_refs(conn, old_fragment, tables=tables)
        ref_sum = sum(counts.values())
        print(f"\n{old_name}: ext {got_ext} -> {want_ext} (sniff); DB rows touching fragment: {ref_sum}")
        for k, v in counts.items():
            if v:
                print(f"  {k}: {v}")

        if new_path.exists():
            print(f"  ERROR target exists, skip: {new_name}", file=sys.stderr)
            exit_code = 1
            continue

        if not apply:
            print("  (dry-run: no copy/DB/fs changes)")
            continue

        shutil.copy2(path, new_path)
        try:
            async with conn.transaction():
                n = await _apply_updates(conn, old_fragment, new_fragment, tables=tables)
                print(f"  DB REPLACE rows updated: {n}")
        except Exception:
            new_path.unlink(missing_ok=True)
            print("  ERROR transaction failed; removed copied file", file=sys.stderr)
            traceback.print_exc()
            exit_code = 1
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            print(f"  warn: could not remove old file {old_name}: {exc}", file=sys.stderr)
            exit_code = 1
        print(f"  ok: removed {old_name}, kept {new_name}")

    await conn.close()
    return exit_code


def main() -> None:
    p = argparse.ArgumentParser(description="Repair media file extensions vs magic bytes.")
    p.add_argument(
        "--env-file",
        "-e",
        type=Path,
        default=None,
        help="Load DATABASE_URL and MEDIA_ROOT from this .env",
    )
    p.add_argument(
        "--media-root",
        type=Path,
        default=None,
        help="Override MEDIA_ROOT",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Copy files, UPDATE database, remove old files (default is dry-run)",
    )
    args = p.parse_args()

    if args.env_file is not None:
        ef = args.env_file.resolve()
        if not ef.is_file():
            print(f"error: env file not found: {ef}", file=sys.stderr)
            sys.exit(1)
        _load_env_file(ef)

    media_root = args.media_root
    if media_root is None:
        mr = os.environ.get("MEDIA_ROOT", "").strip()
        if not mr:
            print("error: MEDIA_ROOT is not set (use env, --env-file, or --media-root)", file=sys.stderr)
            sys.exit(1)
        media_root = Path(mr)

    code = asyncio.run(_run(media_root=media_root, apply=args.apply))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
