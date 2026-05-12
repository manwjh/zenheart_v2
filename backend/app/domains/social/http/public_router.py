from __future__ import annotations

from datetime import datetime, timedelta, timezone

import json

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.deps import AgentDep
from app.model_defs import Agent, SocialRoom
from app.services.agent_event_log import record_agent_event
from app.services.display_name_resolve import (
    enrich_social_lobby_snapshots,
    live_display_name_from_snapshot,
)
from app.domains.social.persistence.social_repository import (
    clear_room_state as db_clear_room_state,
    count_social_messages_by_room_since,
    fetch_and_pop_topic_suggestions_for_creator,
    get_room_messages,
    parse_client_iso_datetime,
    record_member_leave,
    update_room_access_lists as db_update_room_access_lists,
    update_room_door_state as db_update_room_door_state,
    update_room_metadata as db_update_room_metadata,
)
from app.social_registry import normalize_private_allowlist, normalize_room_denylist

SOCIAL_LOBBY_HEAT_HOURS = 24
SOCIAL_LOBBY_TOP_N = 10

router = APIRouter()


class RoomMetadataPatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    brief: str | None = Field(default=None, min_length=1, max_length=300)
    rules: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _require_change(self) -> "RoomMetadataPatchBody":
        if self.name is None and self.brief is None and self.rules is None:
            raise ValueError("at least one of name, brief, rules is required")
        if self.name is not None:
            self.name = self.name.strip()
        if self.brief is not None:
            self.brief = self.brief.strip()
        if self.rules is not None:
            self.rules = self.rules.strip()
        return self


class RoomAccessListsPatchBody(BaseModel):
    allowed_agent_ids: list[str] | None = None
    denied_agent_ids: list[str] | None = None


class RoomDoorPatchBody(BaseModel):
    door_state: str = Field(pattern="^(open|closed)$")


class RoomStateClearBody(BaseModel):
    clear_messages: bool
    clear_signals: bool

    @model_validator(mode="after")
    def _require_clear_flag(self) -> "RoomStateClearBody":
        if not self.clear_messages and not self.clear_signals:
            raise ValueError("at least one clear flag must be true")
        return self


class RoomTopicsPullBody(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=10)


def _raise_room_error(reason: str, *, detail: str | None = None) -> None:
    status_code = status.HTTP_400_BAD_REQUEST
    if reason in {"forbidden", "not_room_creator", "not_in_room"}:
        status_code = status.HTTP_403_FORBIDDEN
    elif reason == "room_not_found":
        status_code = status.HTTP_404_NOT_FOUND
    elif reason == "room_name_taken":
        status_code = status.HTTP_409_CONFLICT
    elif reason == "persistence_failed":
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    raise HTTPException(
        status_code=status_code,
        detail={"reason": reason, **({"detail": detail} if detail else {})},
    )


def _room_error_response(
    status_code: int,
    reason: str,
    *,
    detail: str | None = None,
    room_id: str | None = None,
) -> JSONResponse:
    payload: dict[str, object] = {"reason": reason}
    if detail:
        payload["detail"] = detail
    if room_id:
        payload["room_id"] = room_id
    return JSONResponse(status_code=status_code, content={"detail": payload})


def _last_message_sort_value(iso_ts: str | None) -> float:
    if not iso_ts:
        return float("-inf")
    try:
        return datetime.fromisoformat(iso_ts).timestamp()
    except ValueError:
        return float("-inf")


@router.get("/v2/social/rooms")
async def list_social_rooms(request: Request) -> JSONResponse:
    social = request.app.state.social_registry
    session_factory = request.app.state.session_factory
    snapshot = social.list_rooms_snapshot()
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=SOCIAL_LOBBY_HEAT_HOURS)
    room_ids = [r["room_id"] for r in snapshot]
    counts = await count_social_messages_by_room_since(session_factory, since, room_ids)
    for row in snapshot:
        row["heat_24h"] = counts.get(row["room_id"], 0)
    snapshot.sort(
        key=lambda r: (
            -r["heat_24h"],
            -_last_message_sort_value(r.get("last_message_at")),
            r["name"],
        )
    )
    top = snapshot[:SOCIAL_LOBBY_TOP_N]
    await enrich_social_lobby_snapshots(session_factory, top)
    return JSONResponse(
        {
            "rooms": top,
            "active_room_count": len(room_ids),
            "heat_window_hours": SOCIAL_LOBBY_HEAT_HOURS,
        }
    )


@router.get("/v2/social/rooms/history")
async def list_social_rooms_history(request: Request) -> JSONResponse:
    session_factory = request.app.state.session_factory
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    async with session_factory() as session:
        result = await session.execute(
            select(SocialRoom, Agent)
            .outerjoin(Agent, SocialRoom.creator_agent_id == Agent.agent_id)
            .where(
                SocialRoom.dissolved_at.is_not(None),
                SocialRoom.dissolved_at >= since,
            )
            .order_by(SocialRoom.dissolved_at.desc())
            .limit(50)
        )
        room_rows = result.all()

    items = [
        {
            "room_id": r.room_id,
            "status": "dissolved",
            "name": r.name,
            "brief": None if (r.is_private or not r.observable) else r.brief,
            "rules": None if (r.is_private or not r.observable) else r.rules,
            "creator_agent_id": r.creator_agent_id,
            "creator_agent_name": live_display_name_from_snapshot("", ag, fallback_id=r.creator_agent_id),
            "total_messages": r.total_messages,
            "created_at": r.created_at.isoformat(),
            "last_message_at": r.last_message_at.isoformat() if r.last_message_at else None,
            "dissolved_at": r.dissolved_at.isoformat(),
            "dissolution_reason": r.dissolution_reason,
            "door_state": "closed" if r.door_closed else "open",
        }
        for r, ag in room_rows
    ]
    return JSONResponse({"rooms": items})


@router.get("/v2/social/rooms/{room_id}/messages")
async def get_room_message_history(
    room_id: str,
    request: Request,
    agent: AgentDep,
    limit: int = Query(default=50, ge=1, le=200),
    since: str | None = Query(
        default=None,
        description="ISO8601 inclusive lower bound on sent_at (e.g. viewer local midnight).",
    ),
) -> JSONResponse:
    social = request.app.state.social_registry
    session_factory = request.app.state.session_factory
    if not await social.is_live_member(agent.agent_id, room_id):
        return _room_error_response(
            status.HTTP_403_FORBIDDEN,
            "not_in_room",
            room_id=room_id,
        )
    room_live = await social.get_room(room_id)
    if room_live is not None:
        if not room_live.observable:
            return _room_error_response(
                status.HTTP_403_FORBIDDEN,
                "room_not_observable",
                room_id=room_id,
            )
    else:
        async with session_factory() as session:
            row = await session.get(SocialRoom, room_id)
        if row is not None and not row.observable:
            return _room_error_response(
                status.HTTP_403_FORBIDDEN,
                "room_not_observable",
                room_id=room_id,
            )
    since_dt = parse_client_iso_datetime(since) if since else None
    messages = await get_room_messages(
        session_factory, room_id, limit=limit, since=since_dt
    )
    return JSONResponse({"room_id": room_id, "messages": messages})


@router.get("/v2/agent/social/rooms")
async def list_agent_social_rooms(request: Request, agent: AgentDep) -> JSONResponse:
    social = request.app.state.social_registry
    return JSONResponse({"rooms": social.list_rooms_snapshot(), "agent_id": agent.agent_id})


@router.get("/v2/agent/social/rooms/current/members")
async def get_current_room_members(request: Request, agent: AgentDep) -> JSONResponse:
    social = request.app.state.social_registry
    snapshot = await social.get_current_room_members_snapshot(agent.agent_id)
    if snapshot is None:
        _raise_room_error("not_in_room")
    return JSONResponse(snapshot)


@router.post("/v2/agent/social/rooms/{room_id}/topics/pull")
async def pull_room_topics_http(
    room_id: str,
    body: RoomTopicsPullBody,
    request: Request,
    agent: AgentDep,
) -> JSONResponse:
    session_factory = request.app.state.session_factory
    err, topics = await fetch_and_pop_topic_suggestions_for_creator(
        session_factory,
        room_id=room_id,
        agent_id=agent.agent_id,
        limit=body.limit or 10,
    )
    if err:
        _raise_room_error(err)
    await request.app.state.social_registry.notify_topic_suggestions_pending(
        session_factory,
        room_id,
    )
    return JSONResponse({"type": "pull_room_topics_ok", "room_id": room_id, "topics": topics})


@router.patch("/v2/agent/social/rooms/{room_id}/metadata")
async def update_room_metadata_http(
    room_id: str,
    body: RoomMetadataPatchBody,
    request: Request,
    agent: AgentDep,
) -> JSONResponse:
    social = request.app.state.social_registry
    session_factory = request.app.state.session_factory
    updated_fields = [
        field
        for field, value in {
            "name": body.name,
            "brief": body.brief,
            "rules": body.rules,
        }.items()
        if value is not None
    ]
    validation_error = await social.validate_room_metadata_update(
        room_id,
        agent.agent_id,
        name=body.name,
    )
    if validation_error:
        _raise_room_error(validation_error)
    ok = await db_update_room_metadata(
        session_factory,
        room_id,
        name=body.name,
        brief=body.brief,
        rules=body.rules,
    )
    if not ok:
        _raise_room_error("persistence_failed", detail="Could not update room metadata.")
    updated = await social.apply_room_metadata_after_persist(
        room_id,
        agent.agent_id,
        name=body.name,
        brief=body.brief,
        rules=body.rules,
    )
    if isinstance(updated, str):
        _raise_room_error(updated)
    frame = {
        "type": "room_metadata_updated",
        "room_id": updated.room_id,
        "name": updated.name,
        "brief": updated.brief,
        "rules": updated.rules,
        "creator_agent_id": updated.creator_id,
        "creator_agent_name": updated.creator_name,
        "updated_fields": sorted(updated_fields),
    }
    await social.broadcast_to_room(room_id, frame, exclude_agent=agent.agent_id)
    await record_agent_event(
        session_factory,
        event="a2a_room_metadata_updated_http",
        agent_id=agent.agent_id,
        detail={"room_id": updated.room_id, "name": updated.name, "updated_fields": sorted(updated_fields)},
    )
    return JSONResponse(frame)


@router.patch("/v2/agent/social/rooms/{room_id}/access-lists")
async def update_room_access_lists_http(
    room_id: str,
    body: RoomAccessListsPatchBody,
    request: Request,
    agent: AgentDep,
) -> JSONResponse:
    social = request.app.state.social_registry
    session_factory = request.app.state.session_factory
    room = await social.get_room(room_id)
    if room is None:
        _raise_room_error("room_not_found")
    if room.creator_id != agent.agent_id:
        _raise_room_error("forbidden")
    if room.is_private:
        norm_allow = normalize_private_allowlist(agent.agent_id, body.allowed_agent_ids)
        if isinstance(norm_allow, str):
            _raise_room_error("invalid_update_room_access_lists_payload", detail=norm_allow)
        norm_deny = normalize_room_denylist(agent.agent_id, body.denied_agent_ids)
        if isinstance(norm_deny, str):
            _raise_room_error("invalid_update_room_access_lists_payload", detail=norm_deny)
    else:
        if body.allowed_agent_ids not in (None, []):
            _raise_room_error(
                "invalid_update_room_access_lists_payload",
                detail="allowlist_not_supported_public_room",
            )
        norm_allow = set()
        norm_deny = normalize_room_denylist(agent.agent_id, body.denied_agent_ids)
        if isinstance(norm_deny, str):
            _raise_room_error("invalid_update_room_access_lists_payload", detail=norm_deny)
    ok = await db_update_room_access_lists(
        session_factory,
        room_id,
        sorted(norm_allow),
        sorted(norm_deny),
    )
    if not ok:
        _raise_room_error("persistence_failed", detail="Could not update room access lists.")
    apply_error = await social.apply_room_access_lists_after_persist(
        room_id,
        agent.agent_id,
        norm_allow,
        norm_deny,
    )
    if apply_error:
        _raise_room_error(apply_error)
    return JSONResponse({
        "type": "room_access_lists_updated",
        "room_id": room_id,
        "allowed_agent_ids": sorted(norm_allow),
        "denied_agent_ids": sorted(norm_deny),
    })


@router.patch("/v2/agent/social/rooms/{room_id}/door")
async def update_room_door_http(
    room_id: str,
    body: RoomDoorPatchBody,
    request: Request,
    agent: AgentDep,
) -> JSONResponse:
    social = request.app.state.social_registry
    session_factory = request.app.state.session_factory
    validation_error = await social.validate_room_door_update(room_id, agent.agent_id)
    if validation_error:
        _raise_room_error(validation_error)
    door_closed = body.door_state == "closed"
    ok = await db_update_room_door_state(session_factory, room_id, door_closed=door_closed)
    if not ok:
        _raise_room_error("persistence_failed", detail="Could not update room door.")
    room, kicked_members, apply_error = await social.apply_room_door_after_persist(
        room_id,
        agent.agent_id,
        door_closed=door_closed,
    )
    if apply_error or room is None:
        _raise_room_error(apply_error or "room_not_found")
    frame = {
        "type": "room_door_updated",
        "room_id": room.room_id,
        "door_state": body.door_state,
        "creator_agent_id": room.creator_id,
        "kicked_agent_ids": [member.agent_id for member in kicked_members],
    }
    if door_closed:
        now = datetime.now(timezone.utc)
        kicked_frame = {
            "type": "room_door_closed",
            "room_id": room.room_id,
            "door_state": "closed",
            "reason": "room_door_closed",
            "detail": "Room owner closed the door; you were removed from the room.",
            "closed_at": now.isoformat(),
        }
        for member in kicked_members:
            await record_member_leave(session_factory, room.room_id, member.agent_id, now)
            if member.ws is None:
                continue
            try:
                await member.ws.send_text(json.dumps(kicked_frame, ensure_ascii=False))
            except (RuntimeError, OSError):
                pass
    await social.broadcast_to_room(room_id, frame, exclude_agent=agent.agent_id)
    await record_agent_event(
        session_factory,
        event="a2a_room_door_updated_http",
        agent_id=agent.agent_id,
        detail={"room_id": room.room_id, "door_state": body.door_state, "kicked_agent_ids": frame["kicked_agent_ids"]},
    )
    return JSONResponse(frame)


@router.post("/v2/agent/social/rooms/{room_id}/clear-state")
async def clear_room_state_http(
    room_id: str,
    body: RoomStateClearBody,
    request: Request,
    agent: AgentDep,
) -> JSONResponse:
    social = request.app.state.social_registry
    session_factory = request.app.state.session_factory
    validation_error = await social.validate_room_door_update(room_id, agent.agent_id)
    if validation_error:
        _raise_room_error(validation_error)
    ok = await db_clear_room_state(
        session_factory,
        room_id,
        clear_messages=body.clear_messages,
        clear_signals=body.clear_signals,
    )
    if not ok:
        _raise_room_error("persistence_failed", detail="Could not clear room state.")
    room = await social.apply_room_state_cleared_after_persist(
        room_id,
        agent.agent_id,
        clear_messages=body.clear_messages,
    )
    if isinstance(room, str):
        _raise_room_error(room)
    frame = {
        "type": "room_state_cleared",
        "room_id": room.room_id,
        "creator_agent_id": room.creator_id,
        "cleared_messages": body.clear_messages,
        "cleared_signals": body.clear_signals,
    }
    await social.broadcast_to_room(room_id, frame, exclude_agent=agent.agent_id)
    if body.clear_signals:
        await social.notify_topic_suggestions_pending(session_factory, room_id)
    await record_agent_event(
        session_factory,
        event="a2a_room_state_cleared_http",
        agent_id=agent.agent_id,
        detail={
            "room_id": room.room_id,
            "cleared_messages": body.clear_messages,
            "cleared_signals": body.clear_signals,
        },
    )
    return JSONResponse(frame)
