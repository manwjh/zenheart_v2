"""
Games realtime WebSocket — `/v2/games/ws` (pluggable `game` + `action`, separate from `/v2/agent/ws`).

Handshake: first frame must be registered `auth` (same payload shape as `/v2/agent/ws`). A legacy `anon`
frame is rejected. After `auth_ok`, the `game` + `action` envelope applies; see
`v2/games/games-protocol.md` (also `GET /v2/faq/game/games-protocol`).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.config import Settings
from app.models import Agent
from app.services.agent_event_log import record_agent_event
from app.services.games.maze_ws_side_effects import (
    MazeSideEffectContext,
    apply_maze_ws_side_effects,
)
from app.services.games.ws_inbound_log_policy import should_log_games_ws_message_in
from app.services.games.pomdp_maze import GAME_ID as MAZE_GAME_ID
from app.services.games.pomdp_maze import run_maze_action
from app.services.games_live_registry import GamesLiveRegistry
from app.services.permission_service import get_limit_value
from app.services.ws_auth import (
    _agent_exists_revoked_or_bad,
    verify_agent_auth_payload,
)

# game_id -> handler(old_session, action, data) -> (new_session, outbound_dicts)
GameHandler = Callable[[Any, str, dict[str, Any]], tuple[Any, list[dict[str, Any]]]]

GAME_HANDLERS: dict[str, GameHandler] = {
    MAZE_GAME_ID: run_maze_action,  # type: ignore[assignment]
}
SUPPORTED_GAMES = list(GAME_HANDLERS.keys())


@dataclass(slots=True)
class _GamesIdentity:
    agent_id: str
    level: int
    connection_id: str


def _jdump(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)


async def _perform_games_handshake(
    websocket: WebSocket,
    *,
    settings: Settings,
    session_factory: object,
) -> _GamesIdentity | None:
    """Read first text frame. type=auth: verify registered agent. type=anon: reject. Otherwise close."""
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=float(settings.agent_ws_auth_timeout_seconds),
        )
    except asyncio.TimeoutError:
        await record_agent_event(
            session_factory,
            event="auth_timeout",
            agent_id=None,
            detail={"stage": "first_message", "scope": "games_ws"},
        )
        await websocket.close(code=4408, reason="auth_timeout")
        return None

    byte_len = len(raw.encode("utf-8"))
    if byte_len > settings.agent_ws_max_message_bytes:
        await record_agent_event(
            session_factory,
            event="auth_first_message_too_large",
            agent_id=None,
            detail={"byte_length": byte_len, "scope": "games_ws"},
        )
        await websocket.close(code=1009, reason="too_large")
        return None

    try:
        payload: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        await record_agent_event(
            session_factory,
            event="auth_invalid_json",
            agent_id=None,
            detail={"byte_length": byte_len, "scope": "games_ws"},
        )
        await websocket.send_text(_jdump({"type": "auth_fail", "reason": "invalid_json"}))
        await websocket.close(code=1003, reason="invalid_json")
        return None

    mtype = payload.get("type")
    connection_id = str(uuid.uuid4())

    if mtype == "anon":
        await record_agent_event(
            session_factory,
            event="ws_message_in",
            agent_id=None,
            connection_id=connection_id,
            detail={
                "phase": "handshake",
                "message_type": "anon",
                "byte_length": byte_len,
                "scope": "games_ws",
            },
        )
        await record_agent_event(
            session_factory,
            event="auth_anon_rejected",
            agent_id=None,
            detail={"scope": "games_ws"},
        )
        await websocket.send_text(
            _jdump(
                {
                    "type": "auth_fail",
                    "reason": "anonymous_not_allowed",
                }
            )
        )
        await websocket.close(code=4403, reason="anonymous_not_allowed")
        return None

    if mtype != "auth":
        await record_agent_event(
            session_factory,
            event="auth_expected_type_auth",
            agent_id=None,
            detail={
                "byte_length": byte_len,
                "message_type": mtype,
                "scope": "games_ws",
            },
        )
        await websocket.send_text(
            _jdump(
                {
                    "type": "auth_fail",
                    "reason": "expected_auth",
                }
            )
        )
        await websocket.close(code=1003, reason="expected_auth")
        return None

    agent_id = payload.get("agent_id")
    token = payload.get("token")
    if not isinstance(agent_id, str) or not isinstance(token, str):
        await record_agent_event(
            session_factory,
            event="auth_invalid_payload",
            agent_id=agent_id if isinstance(agent_id, str) else None,
            detail={"byte_length": byte_len, "scope": "games_ws"},
        )
        await websocket.send_text(
            _jdump({"type": "auth_fail", "reason": "invalid_payload"})
        )
        await websocket.close(code=1003, reason="invalid_payload")
        return None

    agent = await verify_agent_auth_payload(
        session_factory,
        agent_id=agent_id,
        token=token,
        event_scope="games_ws",
        byte_length=byte_len,
    )
    if agent is None:
        reason = "unknown_agent"
        code = 4401
        if await _agent_exists_revoked_or_bad(session_factory, agent_id, token):
            async with session_factory() as session:
                row = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
            if row is None:
                reason = "unknown_agent"
            elif row.revoked_at is not None:
                reason = "revoked"
                code = 4403
            else:
                reason = "invalid_token"
        await websocket.send_text(_jdump({"type": "auth_fail", "reason": reason}))
        await websocket.close(code=code, reason=reason)
        return None

    return _GamesIdentity(
        agent_id=agent_id,
        level=agent.level,
        connection_id=connection_id,
    )


async def handle_games_websocket(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    session_factory = websocket.app.state.session_factory

    await websocket.accept()

    ident = await _perform_games_handshake(websocket, settings=settings, session_factory=session_factory)
    if ident is None:
        return

    agent_id = ident.agent_id
    connection_id = ident.connection_id
    tap = getattr(websocket.app.state, "ws_debug_tap", None)

    async def gsend(payload: dict[str, Any]) -> None:
        raw = _jdump(payload)
        if tap is not None:
            await tap.record_outbound_dict(
                channel="games_ws",
                agent_id=agent_id,
                connection_id=connection_id,
                payload=payload,
                raw=raw,
            )
        await websocket.send_text(raw)

    await gsend(
        {
            "type": "auth_ok",
            "connection_id": connection_id,
            "agent_id": ident.agent_id,
            "level": ident.level,
            "server_time": datetime.now(timezone.utc).isoformat(),
            "games_protocol": 1,
            "supported_games": SUPPORTED_GAMES,
        }
    )
    await record_agent_event(
        session_factory,
        event="games_ws_connected",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={"level": ident.level},
    )

    async with session_factory() as _rl_session:
        db_rate_limit = await get_limit_value(_rl_session, "ws", "rate_limit_per_minute")
    rate_limit = (
        db_rate_limit
        if db_rate_limit is not None
        else settings.agent_ws_rate_limit_per_minute
    )
    rate_window: deque[float] = deque(maxlen=rate_limit if rate_limit > 0 else None)
    ws_rate_window = settings.agent_ws_rate_window_seconds
    # Min time between end of one game handler outbound batch and the next accepted `game` frame
    # (pacing is applied *before* that frame consumes a rate slot — avoids racing the hard cap).
    last_game_outbound_at: float | None = None

    game_sessions: dict[str, Any] = {}

    async def _close_rate_limited() -> None:
        await gsend({"type": "error", "reason": "rate_limit_exceeded"})
        await record_agent_event(
            session_factory,
            event="ws_rate_limit_exceeded",
            agent_id=agent_id,
            connection_id=connection_id,
            detail={"rate_limit_per_minute": rate_limit, "scope": "games_ws"},
        )
        await websocket.close(code=4029, reason="rate_limit_exceeded")

    def _append_rate_slot() -> bool:
        """Return False if the sliding window is exceeded (time to close the socket)."""
        if rate_limit <= 0 or rate_window.maxlen is None:
            return True
        now = time.monotonic()
        rate_window.append(now)
        if len(rate_window) == rate_limit and (now - rate_window[0]) < ws_rate_window:
            return False
        return True

    try:
        while True:
            msg = await websocket.receive_text()
            msg_bytes = len(msg.encode("utf-8"))

            if msg_bytes > settings.agent_ws_max_message_bytes:
                await websocket.close(code=1009, reason="too_large")
                break

            try:
                data: dict[str, Any] = json.loads(msg)
            except json.JSONDecodeError:
                await gsend({"type": "error", "reason": "invalid_json"})
                continue

            msg_type = data.get("type")
            if tap is not None and isinstance(data, dict):
                await tap.record_inbound_dict(
                    channel="games_ws",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    byte_len=msg_bytes,
                    data=data,
                )
            if should_log_games_ws_message_in(
                msg_type,
                data,
                log_move_inbound_to_db=settings.games_ws_log_move_inbound_to_db,
            ):
                await record_agent_event(
                    session_factory,
                    event="games_ws_message_in",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": msg_type, "byte_length": msg_bytes},
                )

            if msg_type == "ping":
                if not _append_rate_slot():
                    await _close_rate_limited()
                    break
                await gsend({"type": "pong"})
                continue

            if msg_type == "game":
                raw_gid = data.get("game")
                action = data.get("action")
                if not isinstance(raw_gid, str) or not raw_gid.strip():
                    if not _append_rate_slot():
                        await _close_rate_limited()
                        break
                    await gsend(
                        {
                            "type": "error",
                            "reason": "invalid_game_envelope",
                            "detail": "game must be a non-empty string",
                        }
                    )
                    continue
                if not isinstance(action, str) or not action.strip():
                    if not _append_rate_slot():
                        await _close_rate_limited()
                        break
                    await gsend(
                        {
                            "type": "error",
                            "reason": "invalid_game_envelope",
                            "detail": "action must be a non-empty string",
                        }
                    )
                    continue
                game_id = raw_gid.strip()
                action = action.strip()
                handler = GAME_HANDLERS.get(game_id)
                if handler is None:
                    if not _append_rate_slot():
                        await _close_rate_limited()
                        break
                    await gsend(
                        {
                            "type": "error",
                            "reason": "unknown_game",
                            "supported_games": SUPPORTED_GAMES,
                        }
                    )
                    continue

                # Pacing only for valid `game` (no sliding-window slot): N moves in (N-1)*min_interval
                # can still fill a 120-slot deque within 60s if we also appended here.
                # would still trip a 120-in-60s deque if we also appended here—so dispatch rate is
                # governed solely by sleep vs last_game_outbound_at. The window is for ping / bad frames.
                if rate_limit > 0:
                    min_interval = ws_rate_window / float(rate_limit)
                    if last_game_outbound_at is not None:
                        wait = min_interval - (time.monotonic() - last_game_outbound_at)
                        if wait > 0:
                            await asyncio.sleep(wait)

                old = game_sessions.get(game_id)
                new_sess, out_frames = handler(old, action, data)
                game_sessions[game_id] = new_sess

                live: GamesLiveRegistry = websocket.app.state.games_live_registry
                maze_ctx: MazeSideEffectContext | None = None
                if game_id == MAZE_GAME_ID:
                    maze_ctx = MazeSideEffectContext(
                        connection_id=connection_id,
                        agent_id=agent_id,
                        session_factory=session_factory,
                        live_registry=live,
                    )
                for fr in out_frames:
                    await gsend(fr)
                    if maze_ctx is not None:
                        await apply_maze_ws_side_effects(fr, new_sess, maze_ctx)
                if rate_limit > 0:
                    last_game_outbound_at = time.monotonic()
                continue

            if not _append_rate_slot():
                await _close_rate_limited()
                break
            await gsend({"type": "error", "reason": "unknown_type"})

    except WebSocketDisconnect:
        pass
    finally:
        live_done: GamesLiveRegistry = websocket.app.state.games_live_registry
        await live_done.remove(connection_id)
        await record_agent_event(
            session_factory,
            event="games_ws_disconnected",
            agent_id=agent_id,
            connection_id=connection_id,
            detail={},
        )
