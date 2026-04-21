from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.models import SocialRoom
from app.services.social_db import get_room_messages

router = APIRouter()


@router.get("/v2/social/rooms")
async def list_social_rooms(request: Request) -> JSONResponse:
    social = request.app.state.social_registry
    return JSONResponse({"rooms": social.list_rooms_snapshot()})


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

    Works for both active and dissolved rooms.
    """
    session_factory = request.app.state.session_factory
    messages = await get_room_messages(session_factory, room_id, limit=limit)
    return JSONResponse({"room_id": room_id, "messages": messages})
