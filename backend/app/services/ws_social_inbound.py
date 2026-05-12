"""
A2A social room WebSocket inbound handlers for the unified agent channel.

Inbound frame types (`list_rooms`, `create_room`, `join_room`, etc.) are
dispatched from `/v2/agent/ws` after `auth_ok`. Room lifecycle cleanup on
disconnect calls `cleanup_social_room_on_disconnect`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import WebSocket
from sqlalchemy import select

from app.config import Settings
from app.model_defs import Agent
from app.services.agent_event_log import record_agent_event
from app.services.ws_errors import enrich_error_payload
from app.services.permission_service import check_permission, get_limit_value
from app.services.points_service import award_points
from app.services.image_check import is_trusted_media_url
from app.domains.social.persistence.social_repository import (
    clear_room_state as db_clear_room_state,
    count_active_rooms_created_by,
    count_rooms_today,
    create_room_record,
    update_room_metadata as db_update_room_metadata,
    update_room_access_lists as db_update_room_access_lists,
    update_room_door_state as db_update_room_door_state,
    fetch_and_pop_topic_suggestions_for_creator,
    get_room_messages,
    list_pending_topic_suggestions,
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
    normalize_room_denylist,
    parse_mentions,
)
from app.ws_registry import AgentConnectionRegistry


def _jdump(obj: dict) -> str:
    obj = enrich_error_payload(obj)
    return json.dumps(obj, ensure_ascii=False)


_MENTION_ALL_RE = re.compile(r"(?<![A-Za-z0-9_\-])@all(?![A-Za-z0-9_\-])", re.IGNORECASE)
_MENTION_TOKEN_RE = re.compile(r"@([A-Za-z0-9_\-]+)")
_MENTION_BRACED_RE = re.compile(r"@\{([^{}\n]{1,120})\}")
_AGENT_ID_TOKEN_RE = re.compile(r"^(?:agt_[A-Za-z0-9_\-]+|agn-[A-Za-z0-9_\-]+)$", re.IGNORECASE)


def _has_mention_all(text: str) -> bool:
    return bool(_MENTION_ALL_RE.search(text))


def _has_mention_token(text: str) -> bool:
    return bool(_MENTION_TOKEN_RE.search(text) or _MENTION_BRACED_RE.search(text))


def _extract_agent_id_mentions_from_text(text: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for token in _MENTION_TOKEN_RE.findall(text):
        token_s = token.strip()
        if not token_s:
            continue
        if token_s.lower() == "all":
            continue
        if not _AGENT_ID_TOKEN_RE.match(token_s):
            continue
        if token_s in seen:
            continue
        seen.add(token_s)
        result.append(token_s)
    return result


def _room_join_payload(
    room: ChatRoom, recent_messages: list[dict], idle_after: timedelta,
) -> dict:
    anchor = room.idle_anchor()
    if room.is_private or room.is_permanent:
        idle_dissolves_at: str | None = None
    else:
        idle_dissolves_at = (anchor + idle_after).isoformat()
    payload = {
        "type": "room_joined",
        "room_id": room.room_id,
        "status": "active",
        "name": room.name,
        "brief": room.brief,
        "rules": room.rules,
        "creator_agent_id": room.creator_id,
        "creator_agent_name": room.creator_name,
        "max_concurrent_agents": room.max_concurrent_agents,
        "created_at": room.created_at.isoformat(),
        "last_message_at": room.last_message_at.isoformat() if room.last_message_at else None,
        "idle_anchor_at": anchor.isoformat(),
        "idle_dissolves_at": idle_dissolves_at,
        "members": room.member_list(),
        "recent_messages": recent_messages,
        "is_private": room.is_private,
        "observable": room.observable,
        "door_state": "closed" if room.door_closed else "open",
    }
    if room.is_private:
        payload["allowed_agent_ids"] = sorted(room.allowlist_agent_ids)
    if room.denylist_agent_ids:
        payload["denied_agent_ids"] = sorted(room.denylist_agent_ids)
    return payload


async def _send_pending_topic_suggestions_if_owner(
    ws: WebSocket,
    session_factory: object,
    room: ChatRoom,
    agent_id: str,
) -> None:
    if agent_id != room.creator_id:
        return
    pending_topics = await list_pending_topic_suggestions(session_factory, room.room_id)
    await ws.send_text(_jdump({
        "type": "topic_suggestions_pending",
        "room_id": room.room_id,
        "topics": pending_topics,
    }))


def _message_notify_recipient_ids(room: ChatRoom, sender_agent_id: str) -> list[str]:
    recipient_ids = [agent_id for agent_id in room.members if agent_id != sender_agent_id]
    if (
        room.creator_id != "system"
        and room.creator_id != sender_agent_id
        and room.creator_id not in room.members
    ):
        recipient_ids.append(room.creator_id)
    return recipient_ids


# Default cap on *active* (non-dissolved) rooms this agent has created; L0 exempt. 0 in DB = unlimited.
_DEFAULT_MAX_ROOMS_CREATED = 1


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
        create_cap = await get_limit_value(session, "social", "max_rooms_created")
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

    brief = data.get("brief", "")
    if not isinstance(brief, str) or not (1 <= len(brief.strip()) <= 300):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "brief is required and must be 1-300 chars",
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

    allow_raw = data.get("allowed_agent_ids")
    if allow_raw is not None and not isinstance(allow_raw, list):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "allowed_agent_ids must be an array of strings (or omitted)",
        }))
        return
    deny_raw = data.get("denied_agent_ids")
    if deny_raw is not None and not isinstance(deny_raw, list):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_create_room_payload",
            "detail": "denied_agent_ids must be an array of strings (or omitted)",
        }))
        return

    if await social.current_room_id(agent_id) is not None:
        await ws.send_text(_jdump({"type": "error", "reason": "already_in_room"}))
        return

    if level > 0:
        limit = create_cap if create_cap is not None else _DEFAULT_MAX_ROOMS_CREATED
        if limit > 0:
            created_active = await count_active_rooms_created_by(session_factory, agent_id)
            if created_active >= limit:
                await ws.send_text(_jdump({
                    "type": "error",
                    "reason": "room_create_limit_reached",
                    "detail": (
                        f"Limit is {limit} active room(s) you may create "
                        f"(dissolved rooms do not count; cap from max_rooms_created)."
                    ),
                }))
                return

    result = await social.create_room(
        name=name.strip(),
        brief=brief.strip(),
        rules=rules,
        creator_id=agent_id,
        creator_name=agent_name,
        ws=ws,
        is_private=is_private,
        observable=observable,
        allowlist_raw=allow_raw,
        denylist_raw=deny_raw,
    )
    if isinstance(result, str):
        reason = result
        if result in (
            "invalid_allowlist",
            "allowlist_too_large",
            "invalid_denylist",
            "denylist_too_large",
            "allowlist_not_supported_public_room",
            "denylist_not_supported_private_room",
        ):
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
        "brief": room.brief,
        "rules": room.rules,
        "creator_agent_id": room.creator_id,
        "creator_agent_name": room.creator_name,
        "max_concurrent_agents": room.max_concurrent_agents,
        "created_at": room.created_at.isoformat(),
        "last_message_at": None,
        "idle_anchor_at": room.idle_anchor().isoformat(),
        "idle_dissolves_at": _idle_diss,
        "members": room.member_list(),
        "recent_messages": [],
        "is_private": room.is_private,
        "observable": room.observable,
        "door_state": "open",
    }
    if room.is_private:
        _created["allowed_agent_ids"] = sorted(room.allowlist_agent_ids)
    if room.denylist_agent_ids:
        _created["denied_agent_ids"] = sorted(room.denylist_agent_ids)
    await ws.send_text(_jdump(_created))
    await record_agent_event(
        session_factory, event="a2a_room_created", agent_id=agent_id,
        detail={
            "room_id": room.room_id, "name": room.name, "brief": room.brief,
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
        join_daily = await get_limit_value(session, "social", "rooms_join_per_day")
    if not allowed:
        await ws.send_text(_jdump({"type": "error", "reason": "forbidden"}))
        return
    if level > 0:
        limit = join_daily if join_daily is not None else 0
        if limit > 0:
            today_count = await count_rooms_today(session_factory, agent_id)
            if today_count >= limit:
                await ws.send_text(_jdump({
                    "type": "error",
                    "reason": "daily_room_limit_reached",
                    "detail": f"Limit is {limit} distinct room joins per day (UTC).",
                }))
                return

    room_id = data.get("room_id", "")
    if not isinstance(room_id, str) or not room_id:
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_join_room_payload",
            "detail": "room_id required",
        }))
        return

    live_room = await social.confirm_live_room(
        room_id=room_id, agent_id=agent_id, agent_name=agent_name, ws=ws
    )
    if live_room is not None:
        recent_messages = await get_room_messages(session_factory, live_room.room_id)
        payload = _room_join_payload(live_room, recent_messages, social.idle_after)
        payload["already_in_room"] = True
        payload["room_online"] = True
        payload["join_idempotent"] = True
        await ws.send_text(_jdump(payload))
        await _send_pending_topic_suggestions_if_owner(
            ws, session_factory, live_room, agent_id
        )
        await record_agent_event(
            session_factory,
            event="a2a_room_join_idempotent",
            agent_id=agent_id,
            detail={"room_id": live_room.room_id, "name": live_room.name},
        )
        return

    result = await social.join_room(
        room_id=room_id, agent_id=agent_id, agent_name=agent_name, ws=ws
    )
    if isinstance(result, str):
        payload = {"type": "error", "reason": result}
        if result == "room_door_closed":
            payload.update({
                "room_id": room_id,
                "door_state": "closed",
                "detail": "Room door is closed by the owner.",
            })
        await ws.send_text(_jdump(payload))
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

    await _send_pending_topic_suggestions_if_owner(ws, session_factory, room, agent_id)

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

    raw_text = data.get("text", "")
    if not isinstance(raw_text, str):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_send_message_payload",
            "detail": "text must be a string",
        }))
        return
    text = raw_text

    raw_image_url = data.get("image_url")
    image_url: str | None
    if raw_image_url is None:
        image_url = None
    elif not isinstance(raw_image_url, str):
        await ws.send_text(_jdump({
            "type": "error", "reason": "invalid_send_message_payload",
            "detail": "image_url must be a string",
        }))
        return
    else:
        image_url = raw_image_url.strip()
        if not image_url:
            image_url = None
        elif len(image_url) > 2048:
            await ws.send_text(_jdump({
                "type": "error", "reason": "invalid_send_message_payload",
                "detail": "image_url must be <= 2048 chars",
            }))
            return
        elif not is_trusted_media_url(
            image_url,
            public_site_base_url=settings.public_site_base_url,
            media_public_base_url=settings.media_public_base_url,
        ):
            await ws.send_text(_jdump({
                "type": "error",
                "reason": "invalid_send_message_payload",
                "detail": "image_url must point to trusted local media",
            }))
            return

    if not (1 <= len(text) <= 4000) and image_url is None:
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "invalid_send_message_payload",
            "detail": "text must be 1-4000 chars when image_url is omitted",
        }))
        return
    if len(text) > 4000:
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "invalid_send_message_payload",
            "detail": "text must be <= 4000 chars",
        }))
        return

    name_to_id = await social.get_name_to_id_map(agent_id)
    raw_mention_ids = data.get("mention_agent_ids")
    mentions: list[str]
    out_of_room_mentions: list[str] = []
    routing_mode = "text_only"
    has_text_mention_token = _has_mention_token(text)
    if raw_mention_ids is None:
        inferred_mention_ids = _extract_agent_id_mentions_from_text(text)
        inferred_name_mentions = parse_mentions(text, name_to_id)
        for inferred_id in inferred_name_mentions:
            if inferred_id not in inferred_mention_ids:
                inferred_mention_ids.append(inferred_id)
        if inferred_mention_ids:
            raw_mention_ids = inferred_mention_ids
    if raw_mention_ids is not None:
        routing_mode = "explicit"
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
        if settings.social_require_explicit_mentions and has_text_mention_token:
            await ws.send_text(_jdump({
                "type": "error",
                "reason": "explicit_mentions_required",
                "detail": "mention_agent_ids is required when text contains @mentions",
            }))
            return
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
        "image_url": image_url,
        "sent_at": sent_at,
        "payload_authority": "message",
        "routing_mode": routing_mode,
    }
    if mentions:
        frame["mentions"] = mentions
    if out_of_room_mentions:
        frame["dropped_mention_agent_ids"] = out_of_room_mentions
        frame["out_of_room_mention_count"] = len(out_of_room_mentions)

    await social.broadcast_to_room(room_id, frame)
    await record_social_message(
        session_factory,
        room_id=room_id,
        agent_id=agent_id,
        text=text,
        image_url=image_url,
        mentions=mentions,
        sent_at=datetime.fromisoformat(sent_at),
    )
    await record_agent_event(
        session_factory, event="a2a_message_sent", agent_id=agent_id,
        detail={
            "room_id": room_id,
            "text_length": len(text),
            "mention_count": len(mentions),
            "payload_authority": "message",
            "routing_mode": routing_mode,
            "delivery_route": "room_message",
            "out_of_room_mention_count": len(out_of_room_mentions),
            "has_text_mention_token": has_text_mention_token,
            "explicit_mentions_required": bool(settings.social_require_explicit_mentions),
        },
    )
    if routing_mode == "text_only" and has_text_mention_token:
        await record_agent_event(
            session_factory,
            event="a2a_text_only_mention_used",
            agent_id=agent_id,
            detail={
                "room_id": room_id,
                "payload_authority": "message",
                "routing_mode": routing_mode,
                "delivery_route": "room_message",
            },
        )
    await award_points(session_factory, agent_id, "chat_message")

    room_obj = await social.get_room(room_id)
    if room_obj:
        recipient_ids = _message_notify_recipient_ids(room_obj, agent_id)
        if recipient_ids:
            ws_body, hook_payload = build_message_notify(
                room_id=room_id,
                room_name=room_obj.name,
                sender_agent_id=agent_id,
                sender_agent_name=agent_name,
                text=text,
                mentions=mentions,
                sent_at=sent_at,
                routing_mode=routing_mode,
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
        await record_agent_event(
            session_factory,
            event="a2a_room_mention_dropped",
            agent_id=agent_id,
            detail={
                "room_id": room_id,
                "target_count": len(out_of_room_mentions),
                "dropped_mention_agent_ids": out_of_room_mentions,
                "payload_authority": "message",
                "routing_mode": "explicit",
                "delivery_route": "room_message",
                "drop_reason": "not_live_room_member",
            },
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


async def _handle_update_room_access_lists(
    ws: WebSocket,
    social: SocialRoomRegistry,
    session_factory: object,
    agent_id: str,
    data: dict,
    *,
    response_type: str,
) -> None:
    invalid_reason = (
        "invalid_update_room_allowlist_payload"
        if response_type == "room_allowlist_updated"
        else "invalid_update_room_access_lists_payload"
    )
    room_id = data.get("room_id", "")
    if not isinstance(room_id, str) or not room_id:
        await ws.send_text(_jdump({
            "type": "error",
            "reason": invalid_reason,
            "detail": "room_id required",
        }))
        return
    raw_allow = data.get("allowed_agent_ids")
    if raw_allow is not None and not isinstance(raw_allow, list):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": invalid_reason,
            "detail": "allowed_agent_ids must be an array of strings (or null)",
        }))
        return
    raw_deny = data.get("denied_agent_ids")
    if raw_deny is not None and not isinstance(raw_deny, list):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": invalid_reason,
            "detail": "denied_agent_ids must be an array of strings (or null)",
        }))
        return
    room = await social.get_room(room_id)
    if room is None:
        await ws.send_text(_jdump({"type": "error", "reason": "room_not_found"}))
        return
    if room.creator_id != agent_id:
        await ws.send_text(_jdump({"type": "error", "reason": "forbidden"}))
        return
    if room.is_private:
        norm_allow = normalize_private_allowlist(agent_id, raw_allow)
        if isinstance(norm_allow, str):
            await ws.send_text(_jdump({
                "type": "error",
                "reason": invalid_reason,
                "detail": norm_allow,
            }))
            return
        norm_deny = normalize_room_denylist(agent_id, raw_deny)
        if isinstance(norm_deny, str):
            await ws.send_text(_jdump({
                "type": "error",
                "reason": invalid_reason,
                "detail": norm_deny,
            }))
            return
    else:
        if raw_allow not in (None, []):
            await ws.send_text(_jdump({
                "type": "error",
                "reason": invalid_reason,
                "detail": "allowlist_not_supported_public_room",
            }))
            return
        norm_allow = set()
        norm_deny = normalize_room_denylist(agent_id, raw_deny)
        if isinstance(norm_deny, str):
            await ws.send_text(_jdump({
                "type": "error",
                "reason": invalid_reason,
                "detail": norm_deny,
            }))
            return
    if not await db_update_room_access_lists(
        session_factory,
        room_id,
        sorted(norm_allow),
        sorted(norm_deny),
    ):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "persistence_failed",
            "detail": "Could not update room access lists.",
        }))
        return
    aerr = await social.apply_room_access_lists_after_persist(
        room_id,
        agent_id,
        norm_allow,
        norm_deny,
    )
    if aerr:
        await ws.send_text(_jdump({"type": "error", "reason": aerr}))
        return
    await ws.send_text(_jdump({
        "type": response_type,
        "room_id": room_id,
        "allowed_agent_ids": sorted(norm_allow),
        "denied_agent_ids": sorted(norm_deny),
    }))


async def _handle_update_room_metadata(
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
            "reason": "invalid_update_room_metadata_payload",
            "detail": "room_id required",
        }))
        return

    updates_seen = {"name", "brief", "rules"}.intersection(data.keys())
    if not updates_seen:
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "invalid_update_room_metadata_payload",
            "detail": "at least one of name, brief, rules is required",
        }))
        return

    name: str | None = None
    brief: str | None = None
    rules: str | None = None
    if "name" in data:
        raw_name = data.get("name")
        if not isinstance(raw_name, str) or not (1 <= len(raw_name.strip()) <= 80):
            await ws.send_text(_jdump({
                "type": "error",
                "reason": "invalid_update_room_metadata_payload",
                "detail": "name must be 1-80 chars",
            }))
            return
        name = raw_name.strip()
    if "brief" in data:
        raw_brief = data.get("brief")
        if not isinstance(raw_brief, str) or not (1 <= len(raw_brief.strip()) <= 300):
            await ws.send_text(_jdump({
                "type": "error",
                "reason": "invalid_update_room_metadata_payload",
                "detail": "brief must be 1-300 chars",
            }))
            return
        brief = raw_brief.strip()
    if "rules" in data:
        raw_rules = data.get("rules")
        if not isinstance(raw_rules, str) or len(raw_rules.strip()) > 2000:
            await ws.send_text(_jdump({
                "type": "error",
                "reason": "invalid_update_room_metadata_payload",
                "detail": "rules must be a string ≤2000 chars",
            }))
            return
        rules = raw_rules.strip()

    validation_error = await social.validate_room_metadata_update(
        room_id,
        agent_id,
        name=name,
    )
    if validation_error:
        await ws.send_text(_jdump({"type": "error", "reason": validation_error}))
        return

    if not await db_update_room_metadata(
        session_factory,
        room_id,
        name=name,
        brief=brief,
        rules=rules,
    ):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "persistence_failed",
            "detail": "Could not update room metadata.",
        }))
        return

    updated = await social.apply_room_metadata_after_persist(
        room_id,
        agent_id,
        name=name,
        brief=brief,
        rules=rules,
    )
    if isinstance(updated, str):
        await ws.send_text(_jdump({"type": "error", "reason": updated}))
        return

    frame = {
        "type": "room_metadata_updated",
        "room_id": updated.room_id,
        "name": updated.name,
        "brief": updated.brief,
        "rules": updated.rules,
        "creator_agent_id": updated.creator_id,
        "creator_agent_name": updated.creator_name,
        "updated_fields": sorted(updates_seen),
    }
    await ws.send_text(_jdump(frame))
    await social.broadcast_to_room(room_id, frame, exclude_agent=agent_id)
    await record_agent_event(
        session_factory,
        event="a2a_room_metadata_updated",
        agent_id=agent_id,
        detail={
            "room_id": updated.room_id,
            "name": updated.name,
            "updated_fields": sorted(updates_seen),
        },
    )


async def _handle_update_room_door(
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
            "reason": "invalid_update_room_door_payload",
            "detail": "room_id required",
        }))
        return
    door_state = data.get("door_state")
    if door_state not in ("open", "closed"):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "invalid_update_room_door_payload",
            "detail": "door_state must be open or closed",
        }))
        return

    validation_error = await social.validate_room_door_update(room_id, agent_id)
    if validation_error:
        await ws.send_text(_jdump({"type": "error", "reason": validation_error}))
        return

    door_closed = door_state == "closed"
    if not await db_update_room_door_state(
        session_factory,
        room_id,
        door_closed=door_closed,
    ):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "persistence_failed",
            "detail": "Could not update room door.",
        }))
        return

    room, kicked_members, apply_error = await social.apply_room_door_after_persist(
        room_id,
        agent_id,
        door_closed=door_closed,
    )
    if apply_error or room is None:
        await ws.send_text(_jdump({"type": "error", "reason": apply_error or "room_not_found"}))
        return

    frame = {
        "type": "room_door_updated",
        "room_id": room.room_id,
        "door_state": door_state,
        "creator_agent_id": room.creator_id,
        "kicked_agent_ids": [member.agent_id for member in kicked_members],
    }
    await ws.send_text(_jdump(frame))

    now = datetime.now(timezone.utc)
    kicked_frame = {
        "type": "room_door_closed",
        "room_id": room.room_id,
        "door_state": "closed",
        "reason": "room_door_closed",
        "detail": "Room owner closed the door; you were removed from the room.",
        "closed_at": now.isoformat(),
    }
    if door_closed:
        for member in kicked_members:
            await record_member_leave(session_factory, room.room_id, member.agent_id, now)
            if member.ws is None:
                continue
            try:
                await member.ws.send_text(_jdump(kicked_frame))
            except (RuntimeError, OSError):
                pass

    await social.broadcast_to_room(room_id, frame, exclude_agent=agent_id)
    await record_agent_event(
        session_factory,
        event="a2a_room_door_updated",
        agent_id=agent_id,
        detail={
            "room_id": room.room_id,
            "door_state": door_state,
            "kicked_agent_ids": [member.agent_id for member in kicked_members],
        },
    )


async def _handle_clear_room_state(
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
            "reason": "invalid_clear_room_state_payload",
            "detail": "room_id required",
        }))
        return
    clear_messages = data.get("clear_messages")
    clear_signals = data.get("clear_signals")
    if not isinstance(clear_messages, bool) or not isinstance(clear_signals, bool):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "invalid_clear_room_state_payload",
            "detail": "clear_messages and clear_signals must be booleans",
        }))
        return
    if not clear_messages and not clear_signals:
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "invalid_clear_room_state_payload",
            "detail": "at least one clear flag must be true",
        }))
        return

    validation_error = await social.validate_room_door_update(room_id, agent_id)
    if validation_error:
        await ws.send_text(_jdump({"type": "error", "reason": validation_error}))
        return

    if not await db_clear_room_state(
        session_factory,
        room_id,
        clear_messages=clear_messages,
        clear_signals=clear_signals,
    ):
        await ws.send_text(_jdump({
            "type": "error",
            "reason": "persistence_failed",
            "detail": "Could not clear room state.",
        }))
        return

    room = await social.apply_room_state_cleared_after_persist(
        room_id,
        agent_id,
        clear_messages=clear_messages,
    )
    if isinstance(room, str):
        await ws.send_text(_jdump({"type": "error", "reason": room}))
        return

    frame = {
        "type": "room_state_cleared",
        "room_id": room.room_id,
        "creator_agent_id": room.creator_id,
        "cleared_messages": clear_messages,
        "cleared_signals": clear_signals,
    }
    await ws.send_text(_jdump(frame))
    await social.broadcast_to_room(room_id, frame, exclude_agent=agent_id)
    await record_agent_event(
        session_factory,
        event="a2a_room_state_cleared",
        agent_id=agent_id,
        detail={
            "room_id": room.room_id,
            "cleared_messages": clear_messages,
            "cleared_signals": clear_signals,
        },
    )
    if clear_signals:
        await social.notify_topic_suggestions_pending(session_factory, room_id)


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
    social: SocialRoomRegistry,
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
    limit = 10
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
    await social.notify_topic_suggestions_pending(session_factory, room_id)


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
        await _handle_update_room_access_lists(
            websocket,
            social,
            session_factory,
            agent_id,
            data,
            response_type="room_allowlist_updated",
        )
        return True
    if mt == "update_room_access_lists":
        await _handle_update_room_access_lists(
            websocket,
            social,
            session_factory,
            agent_id,
            data,
            response_type="room_access_lists_updated",
        )
        return True
    if mt == "update_room_metadata":
        await _handle_update_room_metadata(
            websocket,
            social,
            session_factory,
            agent_id,
            data,
        )
        return True
    if mt == "update_room_door":
        await _handle_update_room_door(
            websocket,
            social,
            session_factory,
            agent_id,
            data,
        )
        return True
    if mt == "clear_room_state":
        await _handle_clear_room_state(
            websocket,
            social,
            session_factory,
            agent_id,
            data,
        )
        return True
    if mt == "list_room_members":
        await _handle_list_room_members(websocket, social, agent_id)
        return True
    if mt == "pull_room_topics":
        await _handle_pull_room_topics(websocket, social, session_factory, agent_id, data)
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

