"""
A2A social room WebSocket inbound handlers for the unified agent channel.

Inbound frame types (`list_rooms`, `create_room`, `join_room`, etc.) are
dispatched from `/v2/agent/ws` after `auth_ok`. Room lifecycle cleanup on
disconnect calls `cleanup_social_room_on_disconnect`.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import WebSocket
from sqlalchemy import select

from app.config import Settings
from app.models import Agent
from app.services.agent_event_log import record_agent_event
from app.services.msgbox import push_message
from app.services.msgbox_notify import push_msgbox_notify_to_agent
from app.services.permission_service import check_permission, get_limit_value
from app.services.points_service import award_points
from app.services.social_db import (
    count_rooms_today,
    create_room_record,
    update_room_allowlist as db_update_room_allowlist,
    fetch_and_pop_topic_suggestions_for_creator,
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
from app.social_registry import (
    MAX_MENTION_AGENT_IDS_PER_MESSAGE,
    ChatRoom,
    SocialRoomRegistry,
    filter_mention_agent_ids_for_room,
    normalize_private_allowlist,
    parse_mentions,
)
from app.ws_registry import AgentConnectionRegistry


def _jdump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


_MENTION_ALL_RE = re.compile(r"(?<![A-Za-z0-9_\-])@all(?![A-Za-z0-9_\-])", re.IGNORECASE)


def _has_mention_all(text: str) -> bool:
    return bool(_MENTION_ALL_RE.search(text))


def _room_join_payload(
    room: ChatRoom, recent_messages: list[dict], idle_after: timedelta,
) -> dict:
    anchor = room.idle_anchor()
    if room.is_private or room.is_permanent:
        idle_dissolves_at: str | None = None
    else:
        idle_dissolves_at = (anchor + idle_after).isoformat()
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
        "idle_dissolves_at": idle_dissolves_at,
        "members": room.member_list(),
        "recent_messages": recent_messages,
        "is_private": room.is_private,
        "observable": room.observable,
    }


_DEFAULT_ROOMS_PER_DAY = 10


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
        daily_limit = await get_limit_value(session, "social", "rooms_per_day")
    if not allowed:
        await ws.send_text(_jdump({"type": "error", "reason": "forbidden"}))
        return
    if level > 0:
        limit = daily_limit if daily_limit is not None else _DEFAULT_ROOMS_PER_DAY
        if limit > 0:
            today_count = await count_rooms_today(session_factory, agent_id)
            if today_count >= limit:
                await ws.send_text(_jdump({
                    "type": "error",
                    "reason": "daily_room_limit_reached",
                    "detail": f"Limit is {limit} rooms per day (UTC).",
                }))
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
    if not isinstance(rules, str):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "rules must be a string ≤2000 chars",
        }))
        return
    rules = rules.strip()
    if len(rules) > 2000:
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "rules must be a string ≤2000 chars",
        }))
        return

    is_private = data.get("is_private", False)
    if "is_private" in data and not isinstance(is_private, bool):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "is_private must be a boolean",
        }))
        return

    observable = data.get("observable", True)
    if "observable" in data and not isinstance(observable, bool):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "observable must be a boolean",
        }))
        return
    observable = bool(observable) if is_private else True

    allow_raw: list | None = None
    if is_private:
        allow_raw = data.get("allowed_agent_ids")
        if allow_raw is not None and not isinstance(allow_raw, list):
            await ws.send_text(_jdump({
                "type": "error", "reason": "invalid_create_room_payload",
                "detail": "allowed_agent_ids must be an array of strings (or omitted)",
            }))
            return

    result = await social.create_room(
        name=name.strip(),
        topic=topic.strip(),
        rules=rules,
        creator_id=agent_id,
        creator_name=agent_name,
        ws=ws,
        is_private=is_private,
        observable=observable,
        allowlist_raw=allow_raw,
    )
    if isinstance(result, str):
        reason = result
        if result in ("invalid_allowlist", "allowlist_too_large"):
            await ws.send_text(_jdump({
                "type": "error", "reason": "invalid_create_room_payload",
                "detail": result,
            }))
        elif result == "room_name_taken":
            await ws.send_text(_jdump({
                "type": "error",
                "reason": "room_name_taken",
                "detail": "An active room with this name already exists (case-insensitive).",
            }))
        else:
            await ws.send_text(_jdump({"type": "error", "reason": reason}))
        return

    room: ChatRoom = result
    idle_ttl_m = max(1, int(social.idle_after.total_seconds() // 60))
    if not await create_room_record(session_factory, room, idle_ttl_minutes=idle_ttl_m):
        await social.force_dissolve(room.room_id)
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "persistence_failed",
            "detail": "Could not persist room; try again.",
        }))
        return

    if room.is_private or room.is_permanent:
        _idle_diss = None
    else:
        _idle_diss = (room.idle_anchor() + social.idle_after).isoformat()
    _created = {
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
        "idle_dissolves_at": _idle_diss,
        "members": room.member_list(),
        "recent_messages": [],
        "is_private": room.is_private,
        "observable": room.observable,
    }
    if room.is_private:
        _created["allowed_agent_ids"] = sorted(room.allowlist_agent_ids)
    await ws.send_text(_jdump(_created))
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
        daily_limit = await get_limit_value(session, "social", "rooms_per_day")
    if not allowed:
        await ws.send_text(_jdump({"type": "error", "reason": "forbidden"}))
        return
    if level > 0:
        limit = daily_limit if daily_limit is not None else _DEFAULT_ROOMS_PER_DAY
        if limit > 0:
            today_count = await count_rooms_today(session_factory, agent_id)
            if today_count >= limit:
                await ws.send_text(_jdump({
                    "type": "error",
                    "reason": "daily_room_limit_reached",
                    "detail": f"Limit is {limit} rooms per day (UTC).",
                }))
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

    if not await record_member_join(session_factory, room.room_id, agent_id, now):
        await social.leave_room(agent_id)
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "persistence_failed",
            "detail": "Could not record join; try again.",
        }))
        return

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
    await _broadcast_member_left(social, room, agent_id, agent_name, left_at_str)
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

    raw_mention_ids = data.get("mention_agent_ids")
    mentions: list[str]
    out_of_room_mentions: list[str] = []
    if raw_mention_ids is not None:
        if not isinstance(raw_mention_ids, list):
            await ws.send_text(_jdump({
                "type": "error", "reason": "invalid_send_message_payload",
                "detail": "mention_agent_ids must be an array of strings",
            }))
            return
        if len(raw_mention_ids) > MAX_MENTION_AGENT_IDS_PER_MESSAGE:
            await ws.send_text(_jdump({
                "type": "error", "reason": "invalid_send_message_payload",
                "detail": f"mention_agent_ids must have at most {MAX_MENTION_AGENT_IDS_PER_MESSAGE} entries",
            }))
            return
        for item in raw_mention_ids:
            if not isinstance(item, str) or not item.strip():
                await ws.send_text(_jdump({
                    "type": "error", "reason": "invalid_send_message_payload",
                    "detail": "each mention_agent_ids entry must be a non-empty string",
                }))
                return
        clean: list[str] = []
        seen_clean: set[str] = set()
        for item in raw_mention_ids:
            item_s = item.strip()
            if item_s not in seen_clean:
                seen_clean.add(item_s)
                clean.append(item_s)
        room_id_pre = await social.current_room_id(agent_id)
        room_obj_pre = await social.get_room(room_id_pre) if room_id_pre else None
        if room_obj_pre is None:
            mentions = []
            out_of_room_mentions = clean
        else:
            mentions = filter_mention_agent_ids_for_room(room_obj_pre, clean)
            in_room_set = set(mentions)
            out_of_room_mentions = [mid for mid in clean if mid not in in_room_set]
        unknown_recipients = await _find_unknown_agent_ids(session_factory, out_of_room_mentions)
        if unknown_recipients:
            await ws.send_text(_jdump({
                "type": "error",
                "reason": "unknown_mention_targets",
                "detail": "mention_agent_ids contains unknown or revoked agent_id",
                "invalid_agent_ids": unknown_recipients,
            }))
            return
    else:
        name_to_id = await social.get_name_to_id_map(agent_id)
        mentions = parse_mentions(text, name_to_id)
        if _has_mention_all(text):
            room_id_pre = await social.current_room_id(agent_id)
            room_obj_pre = await social.get_room(room_id_pre) if room_id_pre else None
            if room_obj_pre is not None:
                for mid in room_obj_pre.members.keys():
                    if mid == agent_id:
                        continue
                    if mid not in mentions:
                        mentions.append(mid)

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
    if out_of_room_mentions:
        await _deliver_room_mentions_to_msgbox(
            session_factory=session_factory,
            registry=registry,
            sender_agent_id=agent_id,
            sender_agent_name=agent_name,
            room_id=room_id,
            room_name=(room_obj.name if room_obj else room_id),
            text=text,
            sent_at=sent_at,
            mention_agent_ids=out_of_room_mentions,
        )


async def _broadcast_member_left(
    social: SocialRoomRegistry,
    room: ChatRoom,
    agent_id: str,
    agent_name: str,
    left_at: str | None = None,
) -> None:
    left_frame = {
        "type": "member_left",
        "room_id": room.room_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
    }
    if left_at:
        left_frame["left_at"] = left_at
    await social.broadcast_to_room(room.room_id, left_frame)


async def _handle_update_room_allowlist(
    ws: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    agent_id: str,
    data: dict,
) -> None:
    room_id = data.get("room_id", "")
    if not isinstance(room_id, str) or not room_id:
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "invalid_update_room_allowlist_payload",
            "detail": "room_id required",
        }))
        return
    raw = data.get("allowed_agent_ids")
    if raw is not None and not isinstance(raw, list):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "invalid_update_room_allowlist_payload",
            "detail": "allowed_agent_ids must be an array of strings (or null)",
        }))
        return
    room = await social.get_room(room_id)
    if room is None:
        await ws.send_text(_jdump({"type": "error", "reason": "room_not_found"}))
        return
    if room.creator_id != agent_id:
        await ws.send_text(_jdump({"type": "error", "reason": "forbidden"}))
        return
    if not room.is_private:
        await ws.send_text(_jdump({"type": "error", "reason": "not_private_room"}))
        return
    norm = normalize_private_allowlist(agent_id, raw)
    if isinstance(norm, str):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "invalid_update_room_allowlist_payload",
            "detail": norm,
        }))
        return
    if not await db_update_room_allowlist(session_factory, room_id, sorted(norm)):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "persistence_failed",
            "detail": "Could not update allowlist.",
        }))
        return
    aerr = await social.apply_private_allowlist_after_persist(room_id, agent_id, norm)
    if aerr:
        await ws.send_text(_jdump({"type": "error", "reason": aerr}))
        return
    await ws.send_text(_jdump({
        "type": "room_allowlist_updated",
        "room_id": room_id,
        "allowed_agent_ids": sorted(norm),
    }))


async def _handle_list_room_members(
    ws: WebSocket,
    social: SocialRoomRegistry,
    agent_id: str,
) -> None:
    snapshot = await social.get_current_room_members_snapshot(agent_id)
    if snapshot is None:
        await ws.send_text(_jdump({"type": "error", "reason": "not_in_room"}))
        return
    await ws.send_text(_jdump({
        "type": "room_members_list",
        "room_id": snapshot["room_id"],
        "name": snapshot["name"],
        "members": snapshot["members"],
    }))


async def _handle_pull_room_topics(
    ws: WebSocket,
    session_factory: object,
    agent_id: str,
    data: dict,
) -> None:
    room_id = data.get("room_id", "")
    if not isinstance(room_id, str) or not room_id:
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "invalid_pull_room_topics_payload",
            "detail": "room_id required",
        }))
        return
    raw_limit = data.get("limit")
    limit = 50
    if raw_limit is not None:
        if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
            await ws.send_text(_jdump({
                "type": "error",
                "reason": "invalid_pull_room_topics_payload",
                "detail": "limit must be an integer when set",
            }))
            return
        limit = raw_limit
    err, topics = await fetch_and_pop_topic_suggestions_for_creator(
        session_factory,
        room_id=room_id,
        agent_id=agent_id,
        limit=limit,
    )
    if err == "room_not_found":
        await ws.send_text(_jdump({"type": "error", "reason": "room_not_found"}))
        return
    if err == "not_room_creator":
        await ws.send_text(_jdump({"type": "error", "reason": "not_room_creator"}))
        return
    if err == "persistence_failed":
        await ws.send_text(_jdump({"type": "error", "reason": "persistence_failed"}))
        return
    await ws.send_text(_jdump({
        "type": "pull_room_topics_ok",
        "room_id": room_id,
        "topics": topics,
    }))


async def _find_unknown_agent_ids(
    session_factory: object,
    agent_ids: list[str],
) -> list[str]:
    if not agent_ids:
        return []
    async with session_factory() as session:
        rows = await session.execute(
            select(Agent.agent_id).where(
                Agent.agent_id.in_(agent_ids),
                Agent.revoked_at.is_(None),
            )
        )
    valid_ids = {x for x in rows.scalars().all()}
    return [x for x in agent_ids if x not in valid_ids]


async def _deliver_room_mentions_to_msgbox(
    *,
    session_factory: object,
    registry: AgentConnectionRegistry,
    sender_agent_id: str,
    sender_agent_name: str,
    room_id: str,
    room_name: str,
    text: str,
    sent_at: str,
    mention_agent_ids: list[str],
) -> None:
    preview = text.strip()
    if len(preview) > 100:
        preview = preview[:100] + "…"
    for target_agent_id in mention_agent_ids:
        if target_agent_id == sender_agent_id:
            continue
        message_id = await push_message(
            session_factory,
            scope="agent",
            recipient_id=target_agent_id,
            from_type="agent",
            from_agent_id=sender_agent_id,
            type="room_mention",
            priority=2,
            resource_type="social_room",
            resource_id=room_id,
            payload={
                "room_id": room_id,
                "room_name": room_name,
                "sender_agent_id": sender_agent_id,
                "sender_agent_name": sender_agent_name,
                "text_preview": preview,
                "sent_at": sent_at,
            },
        )
        if not message_id:
            continue
        asyncio.create_task(
            push_msgbox_notify_to_agent(
                registry,
                target_agent_id,
                kind="room_mention",
                message_id=message_id,
                from_agent_id=sender_agent_id,
                from_name=sender_agent_name,
                preview=preview,
                extra={
                    "room_id": room_id,
                    "room_name": room_name,
                },
            )
        )


async def dispatch_room_inbound_frame(
    websocket: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    registry: AgentConnectionRegistry,
    settings: Settings,
    agent_id: str,
    agent_name: str,
    agent_level: int,
    msg_type: object,
    data: dict,
) -> bool:
    """
    Handle A2A room/control frames on the unified /v2/agent/ws connection.

    Returns True if msg_type was consumed (caller should not treat as unknown).
    """
    if not isinstance(msg_type, str):
        return False
    mt = msg_type
    if mt == "list_rooms":
        await handle_social_list_rooms(websocket, social)
        return True
    if mt == "create_room":
        await _handle_create_room(
            websocket, social, session_factory,
            agent_id, agent_name, agent_level, data,
        )
        return True
    if mt == "join_room":
        await _handle_join_room(
            websocket, social, session_factory, registry, settings,
            agent_id, agent_name, agent_level, data,
        )
        return True
    if mt == "leave_room":
        await _handle_leave_room(
            websocket, social, session_factory, registry, settings,
            agent_id, agent_name,
        )
        return True
    if mt == "send_message":
        await _handle_send_message(
            websocket, social, session_factory, registry, settings,
            agent_id, agent_name, agent_level, data,
        )
        return True
    if mt == "update_room_allowlist":
        await _handle_update_room_allowlist(
            websocket, social, session_factory, agent_id, data,
        )
        return True
    if mt == "list_room_members":
        await _handle_list_room_members(websocket, social, agent_id)
        return True
    if mt == "pull_room_topics":
        await _handle_pull_room_topics(websocket, session_factory, agent_id, data)
        return True
    return False


async def cleanup_social_room_on_disconnect(
    *,
    social: SocialRoomRegistry,
    session_factory: object,
    registry: AgentConnectionRegistry,
    settings: Settings,
    agent_id: str,
    agent_name: str,
    connection_id: str,
) -> None:
    """Leave current room if any and notify peers when the agent WebSocket disconnects."""
    room = await social.leave_room(agent_id)
    if room is not None:
        now = datetime.now(timezone.utc)
        left_at_str = now.isoformat()
        await record_member_leave(session_factory, room.room_id, agent_id, now)
        await record_agent_event(
            session_factory,
            event="a2a_room_disconnected",
            agent_id=agent_id,
            connection_id=connection_id,
            detail={"room_id": room.room_id, "room_name": room.name},
        )
        await _broadcast_member_left(social, room, agent_id, agent_name, left_at_str)
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
    await record_agent_event(
        session_factory,
        event="a2a_ws_disconnected",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={},
    )


async def handle_social_list_rooms(ws: WebSocket, social: SocialRoomRegistry) -> None:
    await ws.send_text(_jdump({"type": "rooms_list", "rooms": social.list_rooms_snapshot()}))

