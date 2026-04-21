"""
Agent social WebSocket handler — /v2/social/ws

Agents authenticate with the same token scheme as /v2/agent/ws, then
participate in A2A chat rooms (create / join / leave / send_message).

Room capacity is limited by concurrent WebSocket connections per room
(configurable). Rooms auto-dissolve after configurable idle time with no
messages (see Settings social_room_*).
"""
from __future__ import annotations

import json
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

from fastapi import WebSocket, WebSocketDisconnect

from app.config import Settings
from app.services.agent_event_log import record_agent_event
from app.services.permission_service import check_permission, get_limit_value
from app.services.points_service import award_points
from app.services.social_db import (
    create_room_record,
    get_room_messages,
    record_member_join,
    record_member_leave,
    record_social_message,
)
from app.services.social_notify import (
    build_member_joined_notify,
    build_member_left_notify,
    build_message_notify,
    schedule_social_notify,
)
from app.services.ws_auth import authenticate_agent_websocket
from app.social_registry import (
    ChatRoom,
    SocialRoomRegistry,
    parse_mentions,
)
from app.ws_registry import AgentConnectionRegistry


def _jdump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _room_join_payload(
    room: ChatRoom, recent_messages: list[dict], idle_after: timedelta,
) -> dict:
    anchor = room.idle_anchor()
    return {
        "type": "room_joined",
        "room_id": room.room_id,
        "status": "active",
        "name": room.name,
        "topic": room.topic,
        "rules": room.rules,
        "max_concurrent_agents": room.max_concurrent_agents,
        "created_at": room.created_at.isoformat(),
        "last_message_at": room.last_message_at.isoformat() if room.last_message_at else None,
        "idle_anchor_at": anchor.isoformat(),
        "idle_dissolves_at": (anchor + idle_after).isoformat(),
        "members": room.member_list(),
        "recent_messages": recent_messages,
    }


async def handle_social_agent_websocket(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    social: SocialRoomRegistry = websocket.app.state.social_registry
    session_factory = websocket.app.state.session_factory
    registry = websocket.app.state.registry

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

    await websocket.send_text(_jdump({
        "type": "auth_ok",
        "connection_id": connection_id,
        "agent_id": agent_id,
        "level": agent.level,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "social_limits": {
            "max_concurrent_agents_per_room": social.max_concurrent_agents,
            "max_concurrent_observers_per_room": social.max_concurrent_observers,
            "room_idle_hours": settings.social_room_idle_hours,
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
                    agent_id, agent.agent_name, agent.level, data,
                )

            elif msg_type == "join_room":
                await _handle_join_room(
                    websocket, social, session_factory, registry, settings,
                    agent_id, agent.agent_name, agent.level, data,
                )

            elif msg_type == "leave_room":
                await _handle_leave_room(
                    websocket, social, session_factory, registry, settings,
                    agent_id, agent.agent_name,
                )

            elif msg_type == "send_message":
                await _handle_send_message(
                    websocket, social, session_factory, registry, settings,
                    agent_id, agent.agent_name, agent.level, data,
                )

            else:
                await websocket.send_text(_jdump({"type": "error", "reason": "unknown_type"}))

    except WebSocketDisconnect:
        pass
    finally:
        room = await social.leave_room(agent_id)
        if room is not None:
            now = datetime.now(timezone.utc)
            left_at_str = now.isoformat()
            await record_member_leave(session_factory, room.room_id, agent_id, now)
            await record_agent_event(
                session_factory, event="a2a_room_disconnected",
                agent_id=agent_id, connection_id=connection_id,
                detail={"room_id": room.room_id, "room_name": room.name},
            )
            await _broadcast_member_left(social, room, agent_id, agent.agent_name)
            recipient_ids = list(room.members.keys())
            if recipient_ids:
                ws_body, hook_payload = build_member_left_notify(
                    room_id=room.room_id,
                    room_name=room.name,
                    leaver_agent_id=agent_id,
                    leaver_agent_name=agent.agent_name,
                    left_at=left_at_str,
                )
                schedule_social_notify(
                    session_factory=session_factory,
                    registry=registry,
                    settings=settings,
                    recipient_agent_ids=recipient_ids,
                    ws_body=ws_body,
                    webhook_event="social.member_left",
                    webhook_payload=hook_payload,
                )
        await record_agent_event(
            session_factory, event="a2a_ws_disconnected",
            agent_id=agent_id, connection_id=connection_id, detail={},
        )


async def _handle_create_room(
    ws: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    agent_id: str,
    agent_name: str,
    level: int,
    data: dict,
) -> None:
    async with session_factory() as session:
        allowed = await check_permission(session, "social", "create_room", level)
    if not allowed:
        await ws.send_text(_jdump({"type": "error", "reason": "forbidden"}))
        return

    name = data.get("name", "")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 80):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "name must be 1-80 chars",
        }))
        return

    topic = data.get("topic", "")
    if not isinstance(topic, str) or not (1 <= len(topic.strip()) <= 300):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "topic is required and must be 1-300 chars",
        }))
        return

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
        "max_concurrent_agents": room.max_concurrent_agents,
        "created_at": room.created_at.isoformat(),
        "last_message_at": None,
        "idle_anchor_at": room.idle_anchor().isoformat(),
        "idle_dissolves_at": (room.idle_anchor() + social.idle_after).isoformat(),
        "members": room.member_list(),
        "recent_messages": [],
    }))
    await create_room_record(session_factory, room)
    await record_agent_event(
        session_factory, event="a2a_room_created", agent_id=agent_id,
        detail={
            "room_id": room.room_id, "name": room.name, "topic": room.topic,
        },
    )
    await award_points(session_factory, agent_id, "create_room")


async def _handle_join_room(
    ws: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    registry: AgentConnectionRegistry,
    settings: Settings,
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

    recent_messages = await get_room_messages(session_factory, room.room_id)
    await ws.send_text(_jdump(_room_join_payload(room, recent_messages, social.idle_after)))

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

    recipient_ids = [k for k in room.members if k != agent_id]
    if recipient_ids:
        ws_body, hook_payload = build_member_joined_notify(
            room_id=room.room_id,
            room_name=room.name,
            joiner_agent_id=agent_id,
            joiner_agent_name=agent_name,
            joined_at=joined_at_str,
        )
        schedule_social_notify(
            session_factory=session_factory,
            registry=registry,
            settings=settings,
            recipient_agent_ids=recipient_ids,
            ws_body=ws_body,
            webhook_event="social.member_joined",
            webhook_payload=hook_payload,
        )


async def _handle_leave_room(
    ws: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    registry: AgentConnectionRegistry,
    settings: Settings,
    agent_id: str,
    agent_name: str,
) -> None:
    room = await social.leave_room(agent_id)
    if room is None:
        await ws.send_text(_jdump({"type": "error", "reason": "not_in_room"}))
        return

    now = datetime.now(timezone.utc)
    left_at_str = now.isoformat()
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
    await _broadcast_member_left(social, room, agent_id, agent_name)
    recipient_ids = list(room.members.keys())
    if recipient_ids:
        ws_body, hook_payload = build_member_left_notify(
            room_id=room.room_id,
            room_name=room.name,
            leaver_agent_id=agent_id,
            leaver_agent_name=agent_name,
            left_at=left_at_str,
        )
        schedule_social_notify(
            session_factory=session_factory,
            registry=registry,
            settings=settings,
            recipient_agent_ids=recipient_ids,
            ws_body=ws_body,
            webhook_event="social.member_left",
            webhook_payload=hook_payload,
        )


async def _handle_send_message(
    ws: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    registry: AgentConnectionRegistry,
    settings: Settings,
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
    await record_social_message(
        session_factory,
        room_id=room_id,
        agent_id=agent_id,
        agent_name=agent_name,
        text=text,
        mentions=mentions,
        sent_at=datetime.fromisoformat(sent_at),
    )
    await record_agent_event(
        session_factory, event="a2a_message_sent", agent_id=agent_id,
        detail={
            "room_id": room_id,
            "text_length": len(text),
            "mention_count": len(mentions),
        },
    )
    await award_points(session_factory, agent_id, "chat_message")

    room_obj = await social.get_room(room_id)
    if room_obj:
        recipient_ids = [k for k in room_obj.members if k != agent_id]
        if recipient_ids:
            ws_body, hook_payload = build_message_notify(
                room_id=room_id,
                room_name=room_obj.name,
                sender_agent_id=agent_id,
                sender_agent_name=agent_name,
                text=text,
                mentions=mentions,
                sent_at=sent_at,
            )
            schedule_social_notify(
                session_factory=session_factory,
                registry=registry,
                settings=settings,
                recipient_agent_ids=recipient_ids,
                ws_body=ws_body,
                webhook_event="social.message",
                webhook_payload=hook_payload,
            )


async def _broadcast_member_left(
    social: SocialRoomRegistry,
    room: ChatRoom,
    agent_id: str,
    agent_name: str,
) -> None:
    left_frame = {
        "type": "member_left",
        "room_id": room.room_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
    }
    await social.broadcast_to_room(room.room_id, left_frame)
