"""
Observer WebSocket handler — /v2/social/observe

No authentication required. Humans (or bots) subscribe to one or more
rooms and receive live message/member events. Observers cannot send
messages into rooms.
"""
from __future__ import annotations

import json
import time
from collections import deque

from fastapi import WebSocket, WebSocketDisconnect

from app.services.permission_service import get_limit_value
from app.services.social_db import get_room_messages
from app.social_registry import SocialRoomRegistry


async def handle_social_observe_websocket(websocket: WebSocket) -> None:
    social: SocialRoomRegistry = websocket.app.state.social_registry
    settings = websocket.app.state.settings
    session_factory = websocket.app.state.session_factory

    await websocket.accept()

    async with session_factory() as _rl_session:
        db_rate_limit = await get_limit_value(_rl_session, "ws", "rate_limit_per_minute")
    rate_limit: int = db_rate_limit if db_rate_limit is not None else settings.agent_ws_rate_limit_per_minute
    rate_window: deque[float] = deque(maxlen=rate_limit if rate_limit > 0 else None)

    try:
        while True:
            msg = await websocket.receive_text()

            if rate_limit > 0:
                now = time.monotonic()
                rate_window.append(now)
                if len(rate_window) == rate_limit and (now - rate_window[0]) < 60.0:
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

            elif msg_type == "list_rooms":
                await websocket.send_text(json.dumps({
                    "type": "rooms_list",
                    "rooms": social.list_rooms_snapshot(),
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

                recent_messages = await get_room_messages(session_factory, room.room_id)
                anchor = room.idle_anchor()
                if room.is_private:
                    idle_dissolves = None
                else:
                    idle_dissolves = (anchor + social.idle_after).isoformat()
                await websocket.send_text(json.dumps({
                    "type": "subscribe_ok",
                    "room_id": room.room_id,
                    "status": "active",
                    "name": room.name,
                    "topic": room.topic,
                    "rules": room.rules,
                    "members": room.member_list(),
                    "max_concurrent_agents": room.max_concurrent_agents,
                    "idle_anchor_at": anchor.isoformat(),
                    "idle_dissolves_at": idle_dissolves,
                    "recent_messages": recent_messages,
                    "is_private": room.is_private,
                    "observable": room.observable,
                }, ensure_ascii=False))

            elif msg_type == "unsubscribe":
                room_id = data.get("room_id", "")
                if isinstance(room_id, str) and room_id:
                    await social.remove_observer(room_id, websocket)
                await websocket.send_text(json.dumps({
                    "type": "unsubscribe_ok",
                    "room_id": room_id,
                }))

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
        await social.remove_observer_from_all(websocket)
