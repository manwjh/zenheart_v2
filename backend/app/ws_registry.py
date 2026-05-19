import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from starlette.websockets import WebSocket

from app.services.perception import attach_ws_outbound_perception_if_missing
from app.services.ws_errors import enrich_error_payload

if TYPE_CHECKING:
    from app.services.ws_debug_tap import WsDebugTap


@dataclass
class AgentConnection:
    websocket: WebSocket
    connection_id: str
    send_lock: asyncio.Lock
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AgentConnectionRegistry:
    def __init__(self, debug_tap: Optional["WsDebugTap"] = None) -> None:
        self._lock = asyncio.Lock()
        self._connections_by_agent_id: Dict[str, AgentConnection] = {}
        self._pending_command_results: Dict[tuple[str, str], asyncio.Future[dict[str, Any]]] = {}
        self.debug_tap = debug_tap

    async def list_connections_debug(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return [
                {
                    "agent_id": aid,
                    "connection_id": c.connection_id,
                    "opened_at": c.opened_at.isoformat(),
                }
                for aid, c in sorted(self._connections_by_agent_id.items())
            ]

    async def replace(
        self, agent_id: str, websocket: WebSocket, connection_id: str
    ) -> Optional[WebSocket]:
        async with self._lock:
            previous = self._connections_by_agent_id.get(agent_id)
            self._connections_by_agent_id[agent_id] = AgentConnection(
                websocket=websocket,
                connection_id=connection_id,
                send_lock=asyncio.Lock(),
            )
            if previous is None:
                return None
            return previous.websocket

    async def remove_if_current(self, agent_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            current = self._connections_by_agent_id.get(agent_id)
            if current is not None and current.websocket is websocket:
                del self._connections_by_agent_id[agent_id]
                to_fail: list[asyncio.Future[dict[str, Any]]] = []
                for key, future in list(self._pending_command_results.items()):
                    pending_agent_id, _ = key
                    if pending_agent_id == agent_id:
                        del self._pending_command_results[key]
                        to_fail.append(future)
                for future in to_fail:
                    if not future.done():
                        future.set_exception(RuntimeError("agent_disconnected"))

    async def force_disconnect(
        self,
        agent_id: str,
        message: Dict[str, object],
        close_code: int,
        close_reason: str,
    ) -> None:
        async with self._lock:
            connection = self._connections_by_agent_id.pop(agent_id, None)
            to_fail: list[asyncio.Future[dict[str, Any]]] = []
            for key, future in list(self._pending_command_results.items()):
                pending_agent_id, _ = key
                if pending_agent_id == agent_id:
                    del self._pending_command_results[key]
                    to_fail.append(future)
        if connection is None:
            return
        for future in to_fail:
            if not future.done():
                future.set_exception(RuntimeError(close_reason))
        try:
            raw = json.dumps(message, ensure_ascii=False)
            async with connection.send_lock:
                await connection.websocket.send_text(raw)
            tap = self.debug_tap
            if tap is not None and isinstance(message, dict):
                await tap.record_outbound_dict(
                    channel="agent_ws",
                    agent_id=agent_id,
                    connection_id=connection.connection_id,
                    payload=message,
                    raw=raw,
                )
            await connection.websocket.close(code=close_code, reason=close_reason)
        except Exception:
            pass

    async def dispatch_command_and_wait(
        self,
        agent_id: str,
        request_id: str,
        message: Dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        async with self._lock:
            connection = self._connections_by_agent_id.get(agent_id)
            if connection is None:
                raise RuntimeError("agent_not_connected")
            if (agent_id, request_id) in self._pending_command_results:
                raise RuntimeError("duplicate_request_id")
            result_future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            self._pending_command_results[(agent_id, request_id)] = result_future

        try:
            raw = json.dumps(message, ensure_ascii=False)
            async with connection.send_lock:
                await connection.websocket.send_text(raw)
            tap = self.debug_tap
            if tap is not None and isinstance(message, dict):
                await tap.record_outbound_dict(
                    channel="agent_ws",
                    agent_id=agent_id,
                    connection_id=connection.connection_id,
                    payload=message,
                    raw=raw,
                )
        except Exception as exc:
            async with self._lock:
                self._pending_command_results.pop((agent_id, request_id), None)
            raise RuntimeError("send_failed") from exc

        try:
            return await asyncio.wait_for(result_future, timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("command_timeout") from exc
        finally:
            async with self._lock:
                self._pending_command_results.pop((agent_id, request_id), None)

    async def resolve_command_result(
        self, agent_id: str, request_id: str, payload: dict[str, Any]
    ) -> bool:
        async with self._lock:
            future = self._pending_command_results.get((agent_id, request_id))
        if future is None or future.done():
            return False
        future.set_result(payload)
        return True

    async def get_connection_id(self, agent_id: str) -> Optional[str]:
        async with self._lock:
            connection = self._connections_by_agent_id.get(agent_id)
            if connection is None:
                return None
            return connection.connection_id

    async def connected_agent_ids(self) -> set[str]:
        """Agent IDs with an active /v2/agent/ws in this process (in-memory)."""
        async with self._lock:
            return set(self._connections_by_agent_id.keys())

    async def send_push(self, agent_id: str, payload: Dict[str, Any]) -> bool:
        """Send a JSON frame on /v2/agent/ws if this agent is connected. Best-effort."""
        async with self._lock:
            connection = self._connections_by_agent_id.get(agent_id)
        if connection is None:
            return False
        try:
            sid = "zenheart.net"
            try:
                st = getattr(connection.websocket.app.state, "settings", None)
                if st is not None:
                    sid = (getattr(st, "public_site_base_url", None) or "").strip() or sid
            except Exception:
                sid = "zenheart.net"
            enriched = attach_ws_outbound_perception_if_missing(
                enrich_error_payload(dict(payload)), site_id=sid
            )
            raw = json.dumps(enriched, ensure_ascii=False)
            async with connection.send_lock:
                await connection.websocket.send_text(raw)
            tap = self.debug_tap
            if tap is not None:
                await tap.record_outbound_dict(
                    channel="agent_ws",
                    agent_id=agent_id,
                    connection_id=connection.connection_id,
                    payload=enriched,
                    raw=raw,
                )
            return True
        except Exception:
            return False
