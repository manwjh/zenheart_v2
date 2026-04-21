from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.models import SocialRoom

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
            "max_members": r.max_members,
            "total_messages": r.total_messages,
            "ttl_minutes": r.ttl_minutes,
            "created_at": r.created_at.isoformat(),
            "dissolved_at": r.dissolved_at.isoformat(),
            "dissolution_reason": r.dissolution_reason,
        }
        for r in rooms
    ]
    return JSONResponse({"rooms": items})
