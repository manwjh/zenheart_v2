"""
Observer WebSocket handler — /v2/social/observe

When SOCIAL_OBSERVE_SHARED_TOKEN is set (non-empty), the first frame after connect must be:
  { "type": "auth_observe", "token": "<shared secret>" }
or the same { "type": "auth", "agent_id", "token" } used on /v2/agent/ws.

When the env is unset or empty, the socket accepts traffic immediately (local dev only).

Visitors may enqueue topic suggestions (`submit_topic_suggestion`) for the room
creator to pull on `/v2/agent/ws` (`pull_room_topics`). Those lines are not A2A chat.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.models import Agent
from app.services.agent_event_log import record_agent_event
from app.services.permission_service import get_limit_value
from app.services.display_name_resolve import enrich_member_dicts_live, enrich_social_lobby_snapshots
from app.services.social_db import (
    get_room_messages,
    list_pending_topic_suggestions,
    parse_client_iso_datetime,
    record_room_topic_suggestion,
)
from app.services.ws_auth import verify_agent_auth_payload, verify_observe_shared_token
from app.social_registry import SocialRoomRegistry


async def _observe_handshake_required(
    websocket: WebSocket,
    *,
    session_factory: object,
    settings: object,
) -> bool:
    """If observe token is configured, consume and validate first frame. Returns False on failure (socket closed)."""
    shared = (getattr(settings, "social_observe_shared_token", None) or "").strip()
    if not shared:
        return True

    auth_timeout = int(getattr(settings, "agent_ws_auth_timeout_seconds", 30))
    max_bytes = int(getattr(settings, "agent_ws_max_message_bytes", 65536))

    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=float(auth_timeout),
        )
    except asyncio.TimeoutError:
        await record_agent_event(
            session_factory,
            event="observe_auth_timeout",
            agent_id=None,
            detail={"scope": "observe_ws"},
        )
        await websocket.close(code=4408, reason="observe_auth_timeout")
        return False

    byte_len = len(raw.encode("utf-8"))
    if byte_len > max_bytes:
        await websocket.close(code=1009, reason="too_large")
        return False

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.send_text(
            json.dumps({"type": "auth_fail", "reason": "invalid_json"})
        )
        await websocket.close(code=1003, reason="invalid_json")
        return False

    msg_type = data.get("type")

    if msg_type == "auth_observe":
        tok = data.get("token")
        if not isinstance(tok, str) or not verify_observe_shared_token(tok, shared):
            await websocket.send_text(
                json.dumps({"type": "auth_fail", "reason": "invalid_observe_token"})
            )
            await websocket.close(code=4401, reason="invalid_observe_token")
            return False
        await websocket.send_text(json.dumps({"type": "auth_observe_ok"}))
        return True

    if msg_type == "auth":
        agent_id = data.get("agent_id")
        token = data.get("token")
        if not isinstance(agent_id, str) or not isinstance(token, str):
            await websocket.send_text(
                json.dumps({"type": "auth_fail", "reason": "invalid_payload"})
            )
            await websocket.close(code=1003, reason="invalid_payload")
            return False
        agent = await verify_agent_auth_payload(
            session_factory,
            agent_id=agent_id.strip(),
            token=token,
            event_scope="observe_ws",
            byte_length=byte_len,
        )
        if agent is None:
            reason = "unknown_agent"
            code = 4401
            async with session_factory() as session:
                row = await session.scalar(select(Agent).where(Agent.agent_id == agent_id.strip()))
            if row is None:
                reason = "unknown_agent"
            elif row.revoked_at is not None:
                reason = "revoked"
                code = 4403
            else:
                reason = "invalid_token"
            await websocket.send_text(
                json.dumps({"type": "auth_fail", "reason": reason})
            )
            await websocket.close(code=code, reason=reason)
            return False
        await websocket.send_text(
            json.dumps(
                {
                    "type": "auth_ok",
                    "agent_id": agent.agent_id,
                    "level": agent.level,
                }
            )
        )
        return True

    await websocket.send_text(
        json.dumps({"type": "error", "reason": "observe_auth_required"})
    )
    await websocket.close(code=4401, reason="observe_auth_required")
    return False


async def handle_social_observe_websocket(websocket: WebSocket) -> None:
    social: SocialRoomRegistry = websocket.app.state.social_registry
    settings = websocket.app.state.settings
    session_factory = websocket.app.state.session_factory

    await websocket.accept()

    if not await _observe_handshake_required(
        websocket, session_factory=session_factory, settings=settings
    ):
        return

    async with session_factory() as _rl_session:
        db_rate_limit = await get_limit_value(_rl_session, "ws", "rate_limit_per_minute")
    rate_limit: int = db_rate_limit if db_rate_limit is not None else settings.agent_ws_rate_limit_per_minute
    rate_window: deque[float] = deque()
    last_pong_at = time.monotonic()

    async def _heartbeat_loop() -> None:
        nonlocal last_pong_at
        interval = float(settings.agent_ws_presence_ping_interval_seconds)
        timeout = float(settings.agent_ws_presence_pong_timeout_seconds)
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            if (now - last_pong_at) > timeout:
                await websocket.close(code=4008, reason="pong_timeout")
                return
            await websocket.send_text(json.dumps({"type": "ping"}))

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    try:
        while True:
            msg = await websocket.receive_text()

            if rate_limit > 0:
                now = time.monotonic()
                while rate_window and (now - rate_window[0]) >= 60.0:
                    rate_window.popleft()
                rate_window.append(now)
                if len(rate_window) > rate_limit:
                    await websocket.send_text(
                        json.dumps({"type": "error", "reason": "rate_limit_exceeded"})
                    )
                    await websocket.close(code=4029, reason="rate_limit_exceeded")
                    break

            if len(msg.encode("utf-8")) > settings.agent_ws_max_message_bytes:
                await websocket.close(code=1009, reason="too_large")
                break

            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "reason": "invalid_json"}))
                continue

            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg_type == "pong":
                last_pong_at = time.monotonic()

            elif msg_type == "list_rooms":
                rooms = social.list_rooms_snapshot()
                await enrich_social_lobby_snapshots(session_factory, rooms)
                await websocket.send_text(json.dumps({
                    "type": "rooms_list",
                    "rooms": rooms,
                }))

            elif msg_type == "subscribe":
                room_id = data.get("room_id", "")
                if not isinstance(room_id, str) or not room_id:
                    await websocket.send_text(json.dumps({
                        "type": "subscribe_fail",
                        "reason": "invalid_subscribe_payload",
                        "detail": "room_id required",
                    }))
                    continue

                room, obs_err = await social.add_observer(room_id, websocket)
                if room is None:
                    await websocket.send_text(json.dumps({
                        "type": "subscribe_fail",
                        "reason": obs_err or "room_not_found",
                        "room_id": room_id,
                    }))
                    continue

                raw_since = data.get("messages_since")
                since = parse_client_iso_datetime(raw_since)
                recent_messages = await get_room_messages(
                    session_factory, room.room_id, since=since
                )
                members = room.member_list()
                await enrich_member_dicts_live(session_factory, members)
                anchor = room.idle_anchor()
                if room.is_private or room.is_permanent:
                    idle_dissolves = None
                else:
                    idle_dissolves = (anchor + social.idle_after).isoformat()
                pending_topic_suggestions = await list_pending_topic_suggestions(
                    session_factory, room.room_id
                )
                await websocket.send_text(json.dumps({
                    "type": "subscribe_ok",
                    "room_id": room.room_id,
                    "status": "active",
                    "name": room.name,
                    "topic": room.topic,
                    "rules": room.rules,
                    "members": members,
                    "max_concurrent_agents": room.max_concurrent_agents,
                    "idle_anchor_at": anchor.isoformat(),
                    "idle_dissolves_at": idle_dissolves,
                    "recent_messages": recent_messages,
                    "is_private": room.is_private,
                    "observable": room.observable,
                    "pending_topic_suggestions": pending_topic_suggestions,
                }, ensure_ascii=False))

            elif msg_type == "unsubscribe":
                room_id = data.get("room_id", "")
                if isinstance(room_id, str) and room_id:
                    await social.remove_observer(room_id, websocket)
                await websocket.send_text(json.dumps({
                    "type": "unsubscribe_ok",
                    "room_id": room_id,
                }))

            elif msg_type == "submit_topic_suggestion":
                room_id = data.get("room_id", "")
                text = data.get("text", "")
                if not isinstance(room_id, str) or not room_id or not isinstance(text, str) or not (1 <= len(text) <= 4000):
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "reason": "invalid_submit_topic_payload",
                        "detail": "room_id and text(1-4000) are required",
                    }))
                    continue
                room = await social.get_room(room_id)
                if room is None:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "reason": "room_not_found",
                    }))
                    continue
                if room.is_private:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "reason": "topic_suggestions_disabled_private_room",
                    }))
                    continue
                if not room.observable:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "reason": "not_observable",
                    }))
                    continue
                ok = await record_room_topic_suggestion(session_factory, room_id, text.strip())
                if not ok:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "reason": "persistence_failed",
                    }))
                    continue
                await websocket.send_text(json.dumps({
                    "type": "submit_topic_suggestion_ok",
                    "room_id": room_id,
                }))
                await social.notify_observers_topic_pending(session_factory, room_id)

            else:
                if msg_type in ("send_message", "create_room", "join_room", "leave_room"):
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "reason": "observer_cannot_send",
                    }))
                else:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "reason": "unknown_type",
                    }))

    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        await social.remove_observer_from_all(websocket)
