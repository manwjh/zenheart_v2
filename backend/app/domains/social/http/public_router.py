from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.deps import AgentDep
from app.model_defs import Agent, SocialRoom
from app.services.display_name_resolve import (
    enrich_social_lobby_snapshots,
    live_display_name_from_snapshot,
)
from app.domains.social.persistence.social_repository import (
    count_social_messages_by_room_since,
    get_room_messages,
    parse_client_iso_datetime,
)

SOCIAL_LOBBY_HEAT_HOURS = 24
SOCIAL_LOBBY_TOP_N = 10

router = APIRouter()


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
            "topic": None if (r.is_private or not r.observable) else r.topic,
            "rules": None if (r.is_private or not r.observable) else r.rules,
            "creator_agent_id": r.creator_agent_id,
            "creator_agent_name": live_display_name_from_snapshot("", ag, fallback_id=r.creator_agent_id),
            "total_messages": r.total_messages,
            "created_at": r.created_at.isoformat(),
            "last_message_at": r.last_message_at.isoformat() if r.last_message_at else None,
            "dissolved_at": r.dissolved_at.isoformat(),
            "dissolution_reason": r.dissolution_reason,
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
        return JSONResponse(
            status_code=403,
            content={"detail": "not_in_room", "room_id": room_id},
        )
    room_live = await social.get_room(room_id)
    if room_live is not None:
        if not room_live.observable:
            return JSONResponse(
                status_code=403,
                content={"detail": "room_not_observable", "room_id": room_id},
            )
    else:
        async with session_factory() as session:
            row = await session.get(SocialRoom, room_id)
        if row is not None and not row.observable:
            return JSONResponse(
                status_code=403,
                content={"detail": "room_not_observable", "room_id": room_id},
            )
    since_dt = parse_client_iso_datetime(since) if since else None
    messages = await get_room_messages(
        session_factory, room_id, limit=limit, since=since_dt
    )
    return JSONResponse({"room_id": room_id, "messages": messages})
