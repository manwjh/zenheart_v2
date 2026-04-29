"""
In-memory snapshots of live /v2/games/ws sessions for HTTP + SSE spectators
(`GET /v2/games/active`, `GET /v2/games/stream`).

One row per games WebSocket connection_id that has published at least one maze state.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

MAX_SSE_QUEUE = 1


class GamesLiveRegistry:
    """
    connection_id -> public snapshot. Updated on each maze game_state; removed on WS disconnect.
    Not durable; for observation UI only.

    Listeners: asyncio.Queues for SSE; coalesced push on every publish/remove.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._listeners_lock = asyncio.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._listener_queues: list[asyncio.Queue[str]] = []

    async def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_SSE_QUEUE)
        async with self._listeners_lock:
            self._listener_queues.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        async with self._listeners_lock:
            if q in self._listener_queues:
                self._listener_queues.remove(q)

    async def _notify_listeners(self) -> None:
        snap = await self.list_sessions()
        line = json.dumps({"sessions": snap}, ensure_ascii=False)
        async with self._listeners_lock:
            targets = list(self._listener_queues)
        for q in targets:
            try:
                while not q.empty():
                    q.get_nowait()
                try:
                    q.put_nowait(line)
                except asyncio.QueueFull:
                    while not q.empty():
                        q.get_nowait()
                    q.put_nowait(line)
            except Exception:
                pass

    async def publish_maze(
        self,
        connection_id: str,
        *,
        agent_id: str,
        state: dict[str, Any],
    ) -> None:
        display = agent_id
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "connection_id": connection_id,
            "display_name": display,
            "anonymous": False,
            "agent_id": agent_id,
            "game": "maze",
            "state": state,
            "updated_at": now,
        }
        async with self._lock:
            self._sessions[connection_id] = row
        await self._notify_listeners()

    async def remove(self, connection_id: str) -> None:
        async with self._lock:
            self._sessions.pop(connection_id, None)
        await self._notify_listeners()

    async def list_sessions(self) -> list[dict[str, Any]]:
        async with self._lock:
            out = [dict(s) for s in self._sessions.values()]
        out.sort(key=lambda s: s.get("display_name", ""))
        return out
