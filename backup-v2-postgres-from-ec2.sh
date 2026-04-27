#!/usr/bin/env bash
# Pull a PostgreSQL logical backup of the v2 production database to this machine.
# Only writes a local file — does not import or modify any database.
#
# Requirements:
#   - Same EC2 access as v2/deploy-backend.sh (ZENHEART_EC2_HOST, key, user).
#   - On the server: /opt/zenheart/services/v2_backend/.env with DATABASE_URL.
#   - On the server: app .venv, and a pg_dump whose major version is >= the server
#     (e.g. Postgres 16 in Docker on EC2 needs client 16+; deploy may install pg 15
#     first — this script will try other paths, then "docker run postgres:<major>").
#   - Optional on EC2: ZENHEART_PGDUMP=/path/to/pg_dump
#
# Usage (from repo root or from v2/):
#   ./v2/backup-v2-postgres-from-ec2.sh
#
# Optional:
#   ZENHEART_V2_BACKUP_DIR — output directory (default: <repo>/backups)
#
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$V2_ROOT/.." && pwd)"

die() { echo "error: $*" >&2; exit 1; }

if [[ -f "$V2_ROOT/.deploy-env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$V2_ROOT/.deploy-env"
  set +a
fi

ZENHEART_EC2_KEY="${ZENHEART_EC2_KEY:-$REPO_ROOT/aws/zenheart-ec2.pem}"
ZENHEART_EC2_HOST="${ZENHEART_EC2_HOST:-}"
ZENHEART_EC2_USER="${ZENHEART_EC2_USER:-ec2-user}"
REMOTE_DIR="${ZENHEART_V2_REMOTE_DIR:-/opt/zenheart/services/v2_backend}"
OUT_DIR="${ZENHEART_V2_BACKUP_DIR:-$REPO_ROOT/backups}"

if [[ -z "$ZENHEART_EC2_HOST" ]]; then
  die "ZENHEART_EC2_HOST is not set. Add it to v2/.deploy-env (see v2/.deploy-env.example), same as for deploy-backend.sh."
fi
[[ -f "$ZENHEART_EC2_KEY" ]] || die "SSH key not found: $ZENHEART_EC2_KEY (set ZENHEART_EC2_KEY)"
chmod 400 "$ZENHEART_EC2_KEY" 2>/dev/null || true

SSH_CMD=(
  ssh
  -i "$ZENHEART_EC2_KEY"
  -o StrictHostKeyChecking=accept-new
  -o ServerAliveInterval=5
  -o ConnectTimeout=15
)

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$OUT_DIR/zenheart-v2-pg-$STAMP.dump"
mkdir -p "$OUT_DIR"

echo "[v2-backup] Remote: $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST  DATABASE from $REMOTE_DIR/.env"
echo "[v2-backup] Local file:  $OUT_FILE  (format: pg_dump -Fc, restore with pg_restore)"

run_remote_dump() {
  "${SSH_CMD[@]}" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST" 'bash -s' <<REMOTE
set -euo pipefail
export REMOTE_DIR='${REMOTE_DIR}'
VENV_PY="\${REMOTE_DIR}/.venv/bin/python"
if [[ ! -x "\$VENV_PY" ]]; then
  echo "error: venv python not found: \$VENV_PY" >&2
  exit 1
fi
if [[ ! -f "\${REMOTE_DIR}/.env" ]]; then
  echo "error: missing \${REMOTE_DIR}/.env" >&2
  exit 1
fi
exec "\$VENV_PY" - <<'PY'
import asyncio
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import asyncpg
from sqlalchemy.engine.url import make_url


def _read_database_url(path: Path) -> str:
    raw_url = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^DATABASE_URL=(.*)$", line)
        if m:
            raw_url = m.group(1).strip()
            if (
                len(raw_url) >= 2
                and raw_url[0:1] in '"\''
                and raw_url[-1] == raw_url[0]
            ):
                raw_url = raw_url[1:-1]
            break
    if not raw_url:
        print("error: DATABASE_URL not found in .env", file=sys.stderr)
        sys.exit(1)
    return raw_url


def _pg_dump_major(bin_path: str) -> int | None:
    try:
        out = subprocess.check_output(
            [bin_path, "-V"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    m = re.search(r"(\d+)\.(\d+)", out)
    return int(m.group(1)) if m else None


def _resolve_pg_dump_path(need_major: int) -> str | None:
    cands: list[str] = []
    z = os.environ.get("ZENHEART_PGDUMP", "").strip()
    if z:
        cands.append(z)
    cands.extend(
        [
            "/usr/pgsql-16/bin/pg_dump",
            "/usr/pgsql-17/bin/pg_dump",
            "/usr/lib/postgresql/16/bin/pg_dump",
            "/usr/lib/postgresql/17/bin/pg_dump",
        ]
    )
    for name in ("pg_dump16", "pg_dump"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    seen: set[str] = set()
    for c in cands:
        if not c or c in seen:
            continue
        seen.add(c)
        path = c if c.startswith("/") or "/" in c else (shutil.which(c) or "")
        if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
            continue
        vm = _pg_dump_major(path)
        if vm is not None and vm >= need_major:
            return path
    return None


def _build_docker_pg_dump(
    need_major: int,
    host: str,
    port: int,
    user: str,
    database: str,
    password: str,
) -> list[str] | None:
    if not shutil.which("docker"):
        return None
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "-e",
        f"PGPASSWORD={password}",
        f"postgres:{need_major}",
        "pg_dump",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "--no-owner",
        "--no-acl",
        "-F",
        "c",
        database,
    ]


async def _server_major(dsn: str) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        n = int(await conn.fetchval("show server_version_num"))
        return n // 10000
    finally:
        await conn.close()


def main() -> None:
    remote = os.environ["REMOTE_DIR"]
    path = Path(remote) / ".env"
    if not path.is_file():
        print("error: .env not found at", path, file=sys.stderr)
        sys.exit(1)
    raw_url = _read_database_url(path)
    sync = raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    u = make_url(sync)
    if not u.host or not u.username or u.database is None:
        print("error: could not parse DATABASE_URL host, user, or database", file=sys.stderr)
        sys.exit(1)
    port = u.port or 5432
    password = u.password or ""
    os.environ["PGPASSWORD"] = password

    need_major = asyncio.run(_server_major(sync))
    dumper = _resolve_pg_dump_path(need_major)

    if dumper:
        cmd = [
            dumper,
            "-h",
            u.host,
            "-p",
            str(port),
            "-U",
            u.username,
            "--no-owner",
            "--no-acl",
            "-F",
            "c",
            u.database,
        ]
        env = {**os.environ, "PGPASSWORD": password}
        print(f"info: using pg_dump {dumper} (server major {need_major})", file=sys.stderr)
        subprocess.run(cmd, env=env, check=True)
        return
    dcmd = _build_docker_pg_dump(need_major, u.host, port, u.username, u.database, password)
    if dcmd:
        print(
            f"info: no native pg_dump>={need_major}, using image {dcmd[7]} (docker)",
            file=sys.stderr,
        )
        r = subprocess.run(dcmd, check=False)
        if r.returncode == 0:
            return
        r2 = subprocess.run(["sudo", "-n", *dcmd], check=False)
        if r2.returncode == 0:
            return
    print(
        f"error: need pg_dump for PostgreSQL {need_major}+ (or docker). "
        "On EC2: sudo dnf install -y postgresql16 or set ZENHEART_PGDUMP",
        file=sys.stderr,
    )
    sys.exit(1)


main()
PY
REMOTE
}

if ! run_remote_dump > "$OUT_FILE"; then
  rm -f "$OUT_FILE" 2>/dev/null || true
  die "remote pg_dump failed (SSH, missing deps on server, or DB unreachable from EC2)"
fi

if [[ ! -s "$OUT_FILE" ]]; then
  rm -f "$OUT_FILE" 2>/dev/null || true
  die "backup file is empty; aborting"
fi

echo "[v2-backup] Done. Size: $(du -h "$OUT_FILE" | cut -f1)"
echo "Restore example (to empty database):"
echo "  pg_restore -h 127.0.0.1 -p 5433 -U <user> -d <dbname> -c $OUT_FILE"
