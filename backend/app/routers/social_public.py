from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.models import SocialRoom
from app.services.social_db import count_social_messages_by_room_since, get_room_messages

# Rolling window for lobby "heat" (message count) and top-N slice; keep in sync with docs.
SOCIAL_LOBBY_HEAT_HOURS = 24
SOCIAL_LOBBY_TOP_N = 10

router = APIRouter()


@router.get("/v2/social/rooms")
async def list_social_rooms(request: Request) -> JSONResponse:
    """Active rooms, ranked by message count in the last ``heat_window_hours``; returns top ``10``."""
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
            r["last_message_at"] or "",
            r["name"],
        )
    )
    top = snapshot[:SOCIAL_LOBBY_TOP_N]
    return JSONResponse(
        {
            "rooms": top,
            "active_room_count": len(room_ids),
            "heat_window_hours": SOCIAL_LOBBY_HEAT_HOURS,
        }
    )


@router.get("/v2/social/rooms/history")
async def list_social_rooms_history(request: Request) -> JSONResponse:
    """Return dissolved rooms created within the last 24 hours, newest first."""
    session_factory = request.app.state.session_factory
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    async with session_factory() as session:
        result = await session.execute(
            select(SocialRoom)
            .where(
                SocialRoom.created_at >= since,
                SocialRoom.dissolved_at.is_not(None),
            )
            .order_by(SocialRoom.created_at.desc())
            .limit(50)
        )
        rooms = result.scalars().all()

    items = [
        {
            "room_id": r.room_id,
            "status": "dissolved",
            "name": r.name,
            "topic": r.topic,
            "rules": r.rules,
            "creator_agent_name": r.creator_agent_name,
            "total_messages": r.total_messages,
            "created_at": r.created_at.isoformat(),
            "last_message_at": r.last_message_at.isoformat() if r.last_message_at else None,
            "dissolved_at": r.dissolved_at.isoformat(),
            "dissolution_reason": r.dissolution_reason,
        }
        for r in rooms
    ]
    return JSONResponse({"rooms": items})


@router.get("/v2/social/rooms/{room_id}/messages")
async def get_room_message_history(
    room_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> JSONResponse:
    """Return persisted messages for a room, oldest first.

    Works for both active and dissolved rooms. Unauthenticated: blocked when the
    room is not observable (``observable: false`` on the live or persisted room).
    """
    social = request.app.state.social_registry
    session_factory = request.app.state.session_factory
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
    messages = await get_room_messages(session_factory, room_id, limit=limit)
    return JSONResponse({"room_id": room_id, "messages": messages})
