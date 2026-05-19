#!/usr/bin/env python3
"""
Run a long-lived ZenLink owner client for one room.

The client owns `/v2/agent/ws` for the configured `ZENLINK_AGENT_ID`, joins a
room, watches `topic_suggestions_pending`, replies in-room, and consumes topics
with `pull_room_topics`.

Required env, loaded from backend/.env.zenlink-readiness by default:
  ZENLINK_AGENT_ID
  ZENLINK_TOKEN
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

import websockets

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env.zenlink-readiness"
DEFAULT_BASE_URL = "https://zenheart.net"


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


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required env: {name}")
    return value


def _ws_url(base_url: str) -> str:
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://") :] + "/v2/agent/ws"
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://") :] + "/v2/agent/ws"
    raise RuntimeError("base URL must start with http:// or https://")


def _log(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


async def _send_json(ws: Any, payload: dict[str, Any]) -> None:
    await ws.send(json.dumps(payload, ensure_ascii=False))


async def _recv_json(ws: Any, timeout: float | None = None) -> dict[str, Any]:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout) if timeout else await ws.recv()
    return json.loads(raw)


def _topic_response(topics: list[dict[str, Any]]) -> str:
    texts = [str(topic.get("text") or "").strip() for topic in topics]
    texts = [text for text in texts if text]
    if not texts:
        return "我在，当前没有待处理 topic suggestion。"
    joined = "；".join(texts)
    return f"我在，已收到并处理 topic suggestion：{joined}"


async def _pull_topics(ws: Any, room_id: str, limit: int) -> None:
    await _send_json(ws, {"type": "pull_room_topics", "room_id": room_id, "limit": limit})


async def _handle_topics(ws: Any, room_id: str, topics: list[dict[str, Any]]) -> None:
    if not topics:
        return
    _log({
        "phase": "topics_received",
        "room_id": room_id,
        "topic_count": len(topics),
        "topics": [{"id": t.get("id"), "text": t.get("text")} for t in topics],
    })
    await _send_json(ws, {"type": "send_message", "text": _topic_response(topics)})
    await _pull_topics(ws, room_id, limit=min(10, max(1, len(topics))))


async def run_owner_client(
    *,
    base_url: str,
    agent_id: str,
    token: str,
    room_id: str,
    stop: asyncio.Event,
) -> None:
    ws_url = _ws_url(base_url)
    attempt = 0
    while not stop.is_set():
        attempt += 1
        _log({"phase": "connect_attempt", "attempt": attempt, "room_id": room_id})
        try:
            async with websockets.connect(
                ws_url,
                open_timeout=15,
                close_timeout=5,
                ping_interval=None,
            ) as ws:
                await _send_json(ws, {"type": "auth", "agent_id": agent_id, "token": token})
                auth = await _recv_json(ws, timeout=15)
                _log({
                    "phase": "auth",
                    "type": auth.get("type"),
                    "perception_kind": auth.get("perception_kind"),
                    "anchor": auth.get("anchor"),
                })
                if auth.get("type") != "auth_ok":
                    await asyncio.sleep(5)
                    continue

                await _send_json(ws, {"type": "join_room", "room_id": room_id})
                joined = False
                while not stop.is_set():
                    try:
                        frame = await _recv_json(ws, timeout=20)
                    except asyncio.TimeoutError:
                        await _send_json(ws, {"type": "ping"})
                        continue

                    frame_type = frame.get("type")
                    if frame_type == "ping":
                        await _send_json(ws, {"type": "pong"})
                        _log({"phase": "keepalive", "type": "pong"})
                    elif frame_type == "room_joined":
                        joined = True
                        _log({
                            "phase": "joined",
                            "room_id": frame.get("room_id"),
                            "name": frame.get("name"),
                            "member_count": len(frame.get("members") or []),
                            "perception_kind": frame.get("perception_kind"),
                            "anchor": frame.get("anchor"),
                        })
                    elif frame_type == "topic_suggestions_pending":
                        topics = frame.get("topics") or []
                        _log({
                            "phase": "topic_suggestions_pending",
                            "room_id": frame.get("room_id"),
                            "topic_count": len(topics),
                            "perception_kind": frame.get("perception_kind"),
                            "anchor": frame.get("anchor"),
                        })
                        await _handle_topics(ws, room_id, topics)
                    elif frame_type == "message":
                        _log({
                            "phase": "message_seen",
                            "room_id": frame.get("room_id"),
                            "message_id": frame.get("message_id"),
                            "text": frame.get("text"),
                            "perception_kind": frame.get("perception_kind"),
                        })
                    elif frame_type == "pull_room_topics_ok":
                        _log({
                            "phase": "topics_consumed",
                            "room_id": frame.get("room_id"),
                            "topic_count": len(frame.get("topics") or []),
                            "perception_kind": frame.get("perception_kind"),
                            "anchor": frame.get("anchor"),
                        })
                    elif frame_type == "superseded":
                        _log({"phase": "superseded", "reconnect_in_seconds": 5})
                        break
                    elif frame_type == "error":
                        _log({
                            "phase": "error",
                            "reason": frame.get("reason"),
                            "detail": frame.get("detail"),
                            "joined": joined,
                        })
                        if not joined:
                            break
                    else:
                        _log({
                            "phase": "event",
                            "type": frame_type,
                            "room_id": frame.get("room_id"),
                            "perception_kind": frame.get("perception_kind"),
                            "anchor": frame.get("anchor"),
                            "suggested_action": frame.get("suggested_action"),
                        })
        except Exception as exc:
            _log({
                "phase": "disconnect",
                "error": type(exc).__name__,
                "message": str(exc),
                "reconnect_in_seconds": 5,
            })
        if not stop.is_set():
            await asyncio.sleep(5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a long-lived ZenLink room owner client.")
    parser.add_argument("--room-id", required=True, help="Room id to join and own.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ZENLINK_BASE_URL", DEFAULT_BASE_URL),
        help="ZenLink node base URL.",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Local env file with ZENLINK_AGENT_ID and ZENLINK_TOKEN.",
    )
    args = parser.parse_args()

    _load_env_file(Path(args.env_file))
    agent_id = _require_env("ZENLINK_AGENT_ID")
    token = _require_env("ZENLINK_TOKEN")

    stop = asyncio.Event()

    def request_stop(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    asyncio.run(
        run_owner_client(
            base_url=args.base_url.rstrip("/"),
            agent_id=agent_id,
            token=token,
            room_id=args.room_id,
            stop=stop,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
