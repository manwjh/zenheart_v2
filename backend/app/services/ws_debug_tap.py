"""
In-memory ring buffer of WebSocket traffic for /v2/admin/debug (operator tooling).

Secrets are redacted in previews; presence ping/pong frames are omitted to limit noise.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional


def redact_sensitive(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in {"token", "password", "secret", "refresh_token"} or lk.endswith("_token"):
                out[k] = "[redacted]"
            elif isinstance(v, dict):
                out[k] = redact_sensitive(v)
            elif isinstance(v, list):
                out[k] = redact_sensitive(v)
            else:
                out[k] = v
        return out
    if isinstance(obj, list):
        return [redact_sensitive(x) for x in obj[:80]]
    return obj


@dataclass
class WsDebugEvent:
    seq: int
    ts: str
    channel: str
    direction: str
    agent_id: Optional[str]
    connection_id: Optional[str]
    msg_type: Optional[str]
    byte_len: int
    preview: str


class WsDebugTap:
    def __init__(self, max_events: int = 800) -> None:
        self._seq = 0
        self._events: deque[WsDebugEvent] = deque(maxlen=max_events)
        self._lock = asyncio.Lock()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    @staticmethod
    def _should_skip_presence(msg_type: Any) -> bool:
        return str(msg_type) in ("ping", "pong")

    def _preview(self, payload: Any) -> str:
        try:
            red = redact_sensitive(payload)
            s = json.dumps(red, ensure_ascii=False)
            if len(s) > 600:
                return s[:600] + "…"
            return s
        except Exception:
            return "[unserializable]"

    async def record_inbound_dict(
        self,
        *,
        channel: str,
        agent_id: Optional[str],
        connection_id: Optional[str],
        byte_len: int,
        data: dict[str, Any],
    ) -> None:
        msg_type = data.get("type")
        if self._should_skip_presence(msg_type):
            return
        async with self._lock:
            seq = self._next_seq()
            self._events.append(
                WsDebugEvent(
                    seq=seq,
                    ts=datetime.now(timezone.utc).isoformat(),
                    channel=channel,
                    direction="in",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    msg_type=str(msg_type) if msg_type is not None else None,
                    byte_len=byte_len,
                    preview=self._preview(data),
                )
            )

    async def record_inbound_parse_error(
        self,
        *,
        channel: str,
        agent_id: Optional[str],
        connection_id: Optional[str],
        byte_len: int,
    ) -> None:
        async with self._lock:
            seq = self._next_seq()
            self._events.append(
                WsDebugEvent(
                    seq=seq,
                    ts=datetime.now(timezone.utc).isoformat(),
                    channel=channel,
                    direction="in",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    msg_type=None,
                    byte_len=byte_len,
                    preview="[invalid JSON]",
                )
            )

    async def record_outbound_dict(
        self,
        *,
        channel: str,
        agent_id: Optional[str],
        connection_id: Optional[str],
        payload: dict[str, Any],
        raw: str,
    ) -> None:
        msg_type = payload.get("type")
        if self._should_skip_presence(msg_type):
            return
        byte_len = len(raw.encode("utf-8"))
        async with self._lock:
            seq = self._next_seq()
            self._events.append(
                WsDebugEvent(
                    seq=seq,
                    ts=datetime.now(timezone.utc).isoformat(),
                    channel=channel,
                    direction="out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    msg_type=str(msg_type) if msg_type is not None else None,
                    byte_len=byte_len,
                    preview=self._preview(payload),
                )
            )

    async def events_since(self, since: int, limit: int = 200) -> tuple[list[dict[str, Any]], int]:
        async with self._lock:
            max_seq = self._seq
            rows: list[WsDebugEvent] = [e for e in self._events if e.seq > since]
            rows.sort(key=lambda e: e.seq)
            rows = rows[:limit]
            return [asdict(e) for e in rows], max_seq
