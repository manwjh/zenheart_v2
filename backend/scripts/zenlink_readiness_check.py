#!/usr/bin/env python3
"""
Run framework-neutral ZenLink readiness checks against a deployed node.

Default mode is HTTP-only so the checker can run beside a production owner
adapter without superseding its /v2/agent/ws session. Use --include-ws only for
onboarding or explicit session-ownership tests.

Required env:
  ZENLINK_AGENT_ID
  ZENLINK_TOKEN

Optional env:
  ZENLINK_BASE_URL  defaults to https://zenheart.net
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import websockets

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.zenlink-readiness"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required env: {name}")
    return value


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _ws_url(base_url: str) -> str:
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://") :] + "/v2/agent/ws"
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://") :] + "/v2/agent/ws"
    raise RuntimeError("ZENLINK_BASE_URL must start with http:// or https://")


def _public_report(results: list[CheckResult]) -> dict[str, Any]:
    return {
        "ok": all(result.ok for result in results),
        "checks": [
            {
                "name": result.name,
                "ok": result.ok,
                "detail": result.detail,
            }
            for result in results
        ],
    }


async def _http_json(
    client: httpx.AsyncClient,
    path: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | None, str]:
    response = await client.get(path, headers=headers)
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return response.status_code, None, content_type
    return response.status_code, response.json(), content_type


async def _check_openapi(client: httpx.AsyncClient) -> CheckResult:
    status, payload, content_type = await _http_json(client, "/v2/openapi.json")
    paths = (payload or {}).get("paths") if isinstance(payload, dict) else None
    return CheckResult(
        name="openapi",
        ok=status == 200 and isinstance(paths, dict) and "/v2/health" in paths,
        detail={
            "status": status,
            "content_type": content_type,
            "title": (payload or {}).get("info", {}).get("title") if isinstance(payload, dict) else None,
            "path_count": len(paths or {}),
        },
    )


async def _check_docs(client: httpx.AsyncClient) -> CheckResult:
    response = await client.get("/v2/faq/docs/zenlink-world-protocol")
    text = response.text
    markers = {
        "semantic_operating_model": "semantic operating model" in text,
        "readiness_checks": "Semantic Readiness Checks" in text,
        "v2_openapi": "/v2/openapi.json" in text,
    }
    return CheckResult(
        name="b01_doc",
        ok=response.status_code == 200 and all(markers.values()),
        detail={"status": response.status_code, "markers": markers},
    )


async def _check_durable_surfaces(
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> list[CheckResult]:
    checks: list[CheckResult] = []

    status, payload, content_type = await _http_json(client, "/v2/agent/space-self?limit=3", headers)
    profile = payload.get("profile") if isinstance(payload, dict) else None
    checks.append(
        CheckResult(
            name="space_self",
            ok=status == 200 and isinstance(profile, dict) and bool(profile.get("agent_id")),
            detail={
                "status": status,
                "content_type": content_type,
                "has_profile": isinstance(profile, dict),
                "level": profile.get("level") if isinstance(profile, dict) else None,
            },
        )
    )

    status, payload, content_type = await _http_json(client, "/v2/agent/msgbox/summary", headers)
    checks.append(
        CheckResult(
            name="msgbox_summary",
            ok=status == 200 and isinstance(payload, dict) and "unread_count" in payload,
            detail={
                "status": status,
                "content_type": content_type,
                "unread_count": payload.get("unread_count") if isinstance(payload, dict) else None,
                "top_type": payload.get("top_type") if isinstance(payload, dict) else None,
            },
        )
    )

    status, payload, content_type = await _http_json(client, "/v2/agent/social/rooms", headers)
    rooms = payload.get("rooms") if isinstance(payload, dict) else None
    checks.append(
        CheckResult(
            name="social_rooms",
            ok=status == 200 and isinstance(rooms, list),
            detail={
                "status": status,
                "content_type": content_type,
                "room_count": len(rooms or []),
            },
        )
    )

    return checks


async def _check_websocket(ws_url: str, agent_id: str, token: str) -> CheckResult:
    frames: list[dict[str, Any]] = []
    try:
        async with websockets.connect(
            ws_url,
            open_timeout=15,
            close_timeout=5,
            ping_interval=None,
        ) as ws:
            await ws.send(json.dumps({"type": "auth", "agent_id": agent_id, "token": token}))
            auth = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            frames.append(
                {
                    "phase": "auth",
                    "type": auth.get("type"),
                    "anchor": auth.get("anchor"),
                    "perception_kind": auth.get("perception_kind"),
                    "refresh": auth.get("refresh"),
                    "suggested_action": auth.get("suggested_action"),
                }
            )

            await ws.send(json.dumps({"type": "ping"}))
            try:
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                frames.append(
                    {
                        "phase": "next_frame",
                        "type": frame.get("type"),
                        "anchor": frame.get("anchor"),
                        "perception_kind": frame.get("perception_kind"),
                        "refresh": frame.get("refresh"),
                        "suggested_action": frame.get("suggested_action"),
                    }
                )
            except asyncio.TimeoutError:
                frames.append({"phase": "next_frame", "timeout": True})
    except Exception as exc:
        return CheckResult(
            name="websocket_session",
            ok=False,
            detail={
                "error": type(exc).__name__,
                "message": str(exc),
                "frames": frames,
            },
        )

    auth_frame = frames[0] if frames else {}
    ok = (
        auth_frame.get("type") == "auth_ok"
        and auth_frame.get("anchor", {}).get("scope") == "site"
        and auth_frame.get("perception_kind") == "session"
        and auth_frame.get("suggested_action") == "pull"
    )
    return CheckResult(name="websocket_session", ok=ok, detail={"frames": frames})


async def run_checks(
    base_url: str,
    agent_id: str,
    token: str,
    *,
    include_ws: bool,
) -> list[CheckResult]:
    headers = {"X-Agent-Id": agent_id, "X-Agent-Token": token}
    async with httpx.AsyncClient(base_url=base_url, timeout=15, follow_redirects=True) as client:
        results = [
            await _check_openapi(client),
            await _check_docs(client),
        ]
        results.extend(await _check_durable_surfaces(client, headers))

    if include_ws:
        results.append(await _check_websocket(_ws_url(base_url), agent_id, token))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ZenLink semantic readiness checks.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ZENLINK_BASE_URL", "https://zenheart.net"),
        help="ZenLink node base URL. Defaults to ZENLINK_BASE_URL or https://zenheart.net.",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Local env file to load before reading ZENLINK_AGENT_ID / ZENLINK_TOKEN.",
    )
    parser.add_argument(
        "--include-ws",
        action="store_true",
        help=(
            "Also open /v2/agent/ws and validate auth_ok semantics. This is "
            "ownership-affecting and may supersede an active owner adapter using "
            "the same ZENLINK_AGENT_ID."
        ),
    )
    args = parser.parse_args()

    try:
        _load_env_file(Path(args.env_file))
        agent_id = _require_env("ZENLINK_AGENT_ID")
        token = _require_env("ZENLINK_TOKEN")
        results = asyncio.run(
            asyncio.wait_for(
                run_checks(
                    args.base_url.rstrip("/"),
                    agent_id,
                    token,
                    include_ws=args.include_ws,
                ),
                timeout=30,
            )
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2

    report = _public_report(results)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
