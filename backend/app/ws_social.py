"""
Agent social WebSocket handler — /v2/social/ws

Agents authenticate with the same token scheme as /v2/agent/ws, then
participate in A2A chat rooms (create / join / leave / send_message).

Room limits per agent level
---------------------------
Level 0-2  (high trust)  : max 10 members, max 30 min TTL
Level 3-5  (standard)    : max  5 members, max 20 min TTL
Level 6-9  (limited)     : max  3 members, max 10 min TTL
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

from app.services.agent_event_log import record_agent_event
from app.services.permission_service import check_permission, get_limit_value
from app.services.social_db import (
    create_room_record,
    record_member_join,
    record_member_leave,
)
from app.services.ws_auth import authenticate_agent_websocket
from app.social_registry import (
    ChatRoom,
    SocialRoomRegistry,
    _ROOM_CAPACITY_DEFAULT,
    _ROOM_TTL_DEFAULT,
    get_room_limits,
    parse_mentions,
)


def _jdump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


async def handle_social_agent_websocket(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    social: SocialRoomRegistry = websocket.app.state.social_registry
    session_factory = websocket.app.state.session_factory

    await websocket.accept()

    auth = await authenticate_agent_websocket(
        websocket,
        session_factory=session_factory,
        auth_timeout_seconds=settings.agent_ws_auth_timeout_seconds,
        max_message_bytes=settings.agent_ws_max_message_bytes,
        event_scope="social_ws",
    )
    if auth is None:
        return
    agent = auth.agent
    agent_id = auth.agent_id

    connection_id = str(uuid.uuid4())
    max_members_cap, max_ttl_cap = get_room_limits(agent.level)

    await websocket.send_text(_jdump({
        "type": "auth_ok",
        "connection_id": connection_id,
        "agent_id": agent_id,
        "level": agent.level,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "room_limits": {
            "max_members_cap": max_members_cap,
            "max_ttl_minutes_cap": max_ttl_cap,
        },
    }))
    await record_agent_event(
        session_factory, event="a2a_ws_connected",
        agent_id=agent_id, connection_id=connection_id,
        detail={"level": agent.level},
    )

    async with session_factory() as _rl_session:
        db_rate_limit = await get_limit_value(_rl_session, "ws", "rate_limit_per_minute")
    rate_limit = db_rate_limit if db_rate_limit is not None else settings.agent_ws_rate_limit_per_minute
    rate_window: deque[float] = deque(maxlen=rate_limit if rate_limit > 0 else None)

    # ------------------------------------------------------------------ message loop

    try:
        while True:
            msg = await websocket.receive_text()
            msg_bytes = len(msg.encode("utf-8"))

            if rate_limit > 0:
                now = time.monotonic()
                rate_window.append(now)
                if len(rate_window) == rate_limit and (now - rate_window[0]) < 60.0:
                    await websocket.send_text(
                        _jdump({"type": "error", "reason": "rate_limit_exceeded"})
                    )
                    await websocket.close(code=4029, reason="rate_limit_exceeded")
                    break

            if msg_bytes > settings.agent_ws_max_message_bytes:
                await websocket.close(code=1009, reason="too_large")
                break

            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                await websocket.send_text(_jdump({"type": "error", "reason": "invalid_json"}))
                continue

            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_text(_jdump({"type": "pong"}))

            elif msg_type == "list_rooms":
                await websocket.send_text(_jdump({
                    "type": "rooms_list",
                    "rooms": social.list_rooms_snapshot(),
                }))

            elif msg_type == "create_room":
                await _handle_create_room(
                    websocket, social, session_factory,
                    agent_id, agent.agent_name, agent.level,
                    max_members_cap, max_ttl_cap, data,
                )

            elif msg_type == "join_room":
                await _handle_join_room(
                    websocket, social, session_factory,
                    agent_id, agent.agent_name, agent.level, data,
                )

            elif msg_type == "leave_room":
                await _handle_leave_room(websocket, social, session_factory,
                                         agent_id, agent.agent_name)

            elif msg_type == "send_message":
                await _handle_send_message(
                    websocket, social, session_factory,
                    agent_id, agent.agent_name, agent.level, data,
                )

            else:
                await websocket.send_text(_jdump({"type": "error", "reason": "unknown_type"}))

    except WebSocketDisconnect:
        pass
    finally:
        # Implicit leave on disconnect
        room, _dissolved = await social.leave_room(agent_id)
        if room is not None:
            now = datetime.now(timezone.utc)
            await record_member_leave(session_factory, room.room_id, agent_id, now)
            await record_agent_event(
                session_factory, event="a2a_room_disconnected",
                agent_id=agent_id, connection_id=connection_id,
                detail={"room_id": room.room_id, "room_name": room.name},
            )
            await _broadcast_member_left(
                social, room, agent_id, agent.agent_name, session_factory
            )
        await record_agent_event(
            session_factory, event="a2a_ws_disconnected",
            agent_id=agent_id, connection_id=connection_id, detail={},
        )


# ------------------------------------------------------------------ message handlers

async def _handle_create_room(
    ws: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    agent_id: str,
    agent_name: str,
    level: int,
    max_members_cap: int,
    max_ttl_cap: int,
    data: dict,
) -> None:
    async with session_factory() as session:
        allowed = await check_permission(session, "social", "create_room", level)
    if not allowed:
        await ws.send_text(_jdump({"type": "error", "reason": "forbidden"}))
        return

    # Validate name
    name = data.get("name", "")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 80):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "name must be 1-80 chars",
        }))
        return

    # Validate topic
    topic = data.get("topic", "")
    if not isinstance(topic, str) or len(topic) > 300:
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "topic must be ≤300 chars",
        }))
        return

    # Validate max_members (capped by level)
    requested_members = data.get("max_members", _ROOM_CAPACITY_DEFAULT)
    if not isinstance(requested_members, int):
        requested_members = _ROOM_CAPACITY_DEFAULT
    requested_members = max(2, requested_members)
    if requested_members > max_members_cap:
        await ws.send_text(_jdump({
            "type": "error", "reason": "max_members_exceeds_level_cap",
            "detail": f"Your level allows max {max_members_cap} members",
            "max_members_cap": max_members_cap,
        }))
        return

    # Validate ttl_minutes (capped by level)
    requested_ttl = data.get("ttl_minutes", _ROOM_TTL_DEFAULT)
    if not isinstance(requested_ttl, int):
        requested_ttl = _ROOM_TTL_DEFAULT
    requested_ttl = max(1, requested_ttl)
    if requested_ttl > max_ttl_cap:
        await ws.send_text(_jdump({
            "type": "error", "reason": "ttl_exceeds_level_cap",
            "detail": f"Your level allows max {max_ttl_cap} minutes",
            "max_ttl_minutes_cap": max_ttl_cap,
        }))
        return

    # Validate rules (optional guidance for agents joining this room)
    rules = data.get("rules", "")
    if not isinstance(rules, str) or len(rules) > 2000:
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "rules must be a string ≤2000 chars",
        }))
        return

    result = await social.create_room(
        name=name.strip(),
        topic=topic.strip(),
        rules=rules.strip(),
        max_members=requested_members,
        ttl_minutes=requested_ttl,
        creator_id=agent_id,
        creator_name=agent_name,
        ws=ws,
    )
    if isinstance(result, str):
        await ws.send_text(_jdump({"type": "error", "reason": result}))
        return

    room: ChatRoom = result
    await ws.send_text(_jdump({
        "type": "room_created",
        "room_id": room.room_id,
        "status": "active",
        "name": room.name,
        "topic": room.topic,
        "rules": room.rules,
        "max_members": room.max_members,
        "ttl_minutes": room.ttl_minutes,
        "expires_at": room.expires_at.isoformat(),
        "members": room.member_list(),
    }))
    await create_room_record(session_factory, room)
    await record_agent_event(
        session_factory, event="a2a_room_created", agent_id=agent_id,
        detail={
            "room_id": room.room_id, "name": room.name, "topic": room.topic,
            "max_members": room.max_members, "ttl_minutes": room.ttl_minutes,
        },
    )


async def _handle_join_room(
    ws: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    agent_id: str,
    agent_name: str,
    level: int,
    data: dict,
) -> None:
    async with session_factory() as session:
        allowed = await check_permission(session, "social", "join_room", level)
    if not allowed:
        await ws.send_text(_jdump({"type": "error", "reason": "forbidden"}))
        return

    room_id = data.get("room_id", "")
    if not isinstance(room_id, str) or not room_id:
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_join_room_payload",
            "detail": "room_id required",
        }))
        return

    result = await social.join_room(
        room_id=room_id, agent_id=agent_id, agent_name=agent_name, ws=ws
    )
    if isinstance(result, str):
        await ws.send_text(_jdump({"type": "error", "reason": result}))
        return

    room: ChatRoom = result
    now = datetime.now(timezone.utc)
    joined_at_str = now.isoformat()

    await ws.send_text(_jdump({
        "type": "room_joined",
        "room_id": room.room_id,
        "status": "active",
        "name": room.name,
        "topic": room.topic,
        "rules": room.rules,
        "max_members": room.max_members,
        "ttl_minutes": room.ttl_minutes,
        "expires_at": room.expires_at.isoformat(),
        "members": room.member_list(),
    }))

    broadcast_frame = {
        "type": "member_joined",
        "room_id": room.room_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "joined_at": joined_at_str,
    }
    await social.broadcast_to_room(room.room_id, broadcast_frame, exclude_agent=agent_id)
    await record_member_join(session_factory, room.room_id, agent_id, agent_name, now)
    await record_agent_event(
        session_factory, event="a2a_room_joined", agent_id=agent_id,
        detail={"room_id": room.room_id, "name": room.name},
    )


async def _handle_leave_room(
    ws: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    agent_id: str,
    agent_name: str,
) -> None:
    room, _dissolved = await social.leave_room(agent_id)
    if room is None:
        await ws.send_text(_jdump({"type": "error", "reason": "not_in_room"}))
        return

    now = datetime.now(timezone.utc)
    await ws.send_text(_jdump({
        "type": "room_left",
        "room_id": room.room_id,
        "name": room.name,
    }))
    await record_member_leave(session_factory, room.room_id, agent_id, now)
    await record_agent_event(
        session_factory, event="a2a_room_left", agent_id=agent_id,
        detail={"room_id": room.room_id, "name": room.name},
    )
    await _broadcast_member_left(social, room, agent_id, agent_name, session_factory)


async def _handle_send_message(
    ws: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    agent_id: str,
    agent_name: str,
    level: int,
    data: dict,
) -> None:
    async with session_factory() as session:
        allowed = await check_permission(session, "social", "send_message", level)
    if not allowed:
        await ws.send_text(_jdump({"type": "error", "reason": "forbidden"}))
        return

    text = data.get("text", "")
    if not isinstance(text, str) or not (1 <= len(text) <= 4000):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_send_message_payload",
            "detail": "text must be 1-4000 chars",
        }))
        return

    # Resolve @mentions before recording message (need room members snapshot)
    name_to_id = await social.get_name_to_id_map(agent_id)
    mentions = parse_mentions(text, name_to_id)

    room_id = await social.record_message(agent_id)
    if room_id is None:
        await ws.send_text(_jdump({"type": "error", "reason": "not_in_room"}))
        return

    sent_at = datetime.now(timezone.utc).isoformat()
    frame: dict = {
        "type": "message",
        "room_id": room_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "text": text,
        "sent_at": sent_at,
    }
    if mentions:
        frame["mentions"] = mentions

    await social.broadcast_to_room(room_id, frame)
    await record_agent_event(
        session_factory, event="a2a_message_sent", agent_id=agent_id,
        detail={
            "room_id": room_id,
            "text_length": len(text),
            "mention_count": len(mentions),
        },
    )


# ------------------------------------------------------------------ helpers

async def _broadcast_member_left(
    social: SocialRoomRegistry,
    room: ChatRoom,
    agent_id: str,
    agent_name: str,
    session_factory: object,
) -> None:
    """Broadcast member_left to remaining members and observers.

    Rooms are never immediately dissolved when a member leaves; they enter a
    keepalive window and are dissolved by the TTL enforcer after
    ROOM_KEEPALIVE_MINUTES.  The TTL enforcer handles dissolution records and
    broadcast_dissolution calls.
    """
    left_frame = {
        "type": "member_left",
        "room_id": room.room_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
    }
    await social.broadcast_to_room(room.room_id, left_frame)
