#!/usr/bin/env python3
"""Turn cursor_agent.py `start` stdout (JSON line(s)) into a short human message."""
from __future__ import annotations

import json
import pathlib
import sys


def squash(s: str) -> str:
    return " ".join(s.split())


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: summarize_start_stdout.py /path/to/captured_stdout", file=sys.stderr)
        return 2

    raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        print("(start produced no stdout)", file=sys.stderr)
        return 1

    picked: dict | None = None
    for ln in reversed(raw.splitlines()):
        cand = ln.strip()
        if not cand.startswith("{") or not cand.endswith("}"):
            continue
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("ok" in parsed or "error" in parsed):
            picked = parsed
            break

    if picked is None:
        print("[START RAW]", squash(raw)[:500])
        return 0

    if picked.get("ok") is True:
        pid = picked.get("pid")
        rd = picked.get("runtime_dir")
        print(squash("[START OK] daemon pid=" + str(pid if pid is not None else "?")))
        if rd:
            print("  workspace: " + str(rd))
        return 0

    err = str(picked.get("error") or "?")
    msg = str(picked.get("message") or "").strip()
    print(squash(f"[START FAIL] {err} {msg}")[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
