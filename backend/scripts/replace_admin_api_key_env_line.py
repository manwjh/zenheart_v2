#!/usr/bin/env python3
"""Rewrite ADMIN_API_KEY=… in a .env file (one logical line; value may be unquoted)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: replace_admin_api_key_env_line.py <path-to-.env> <new-key>", file=sys.stderr)
        sys.exit(2)
    path = Path(sys.argv[1])
    new_key = sys.argv[2]
    if not path.is_file():
        print(f"error: not a file: {path}", file=sys.stderr)
        sys.exit(1)
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    out: list[str] = []
    found = False
    prefix = "ADMIN_API_KEY="
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and s.startswith(prefix):
            out.append(f"{prefix}{new_key}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip() != "":
            out.append("")
        out.append(f"{prefix}{new_key}")
    text = "\n".join(out)
    if raw.endswith("\n") or not raw:
        path.write_text(text + "\n", encoding="utf-8")
    else:
        path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


if __name__ == "__main__":
    main()
