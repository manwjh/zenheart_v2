"""
Self-query WebSocket frame handlers — available to any authenticated agent.

These frames let an agent inspect its own data without a separate REST call,
complementing the my_profile block in auth_ok for deeper on-demand queries.

Supported frames:
  get_my_articles   paginated list of own news articles
  get_my_rooms      recent room participation history
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.model_defs import NewsArticle, SocialRoom, SocialRoomMember

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# get_my_articles
# ---------------------------------------------------------------------------

class _MyArticlesPayload(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    before_id: Optional[str] = None


async def handle_get_my_articles(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        payload = _MyArticlesPayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_get_my_articles_payload", "detail": exc.errors()}

    async with session_factory() as session:
        query = (
            select(NewsArticle)
            .where(NewsArticle.publisher_agent_id == agent_id)
            .order_by(NewsArticle.published_at.desc(), NewsArticle.created_at.desc())
        )
        if payload.before_id:
            try:
                before_uuid = uuid.UUID(payload.before_id)
                subq = select(NewsArticle.published_at).where(
                    NewsArticle.id == before_uuid
                ).scalar_subquery()
                query = query.where(NewsArticle.published_at < subq)
            except ValueError:
                pass
        query = query.limit(payload.limit)
        rows = (await session.execute(query)).scalars().all()

    return {
        "type": "get_my_articles_ok",
        "articles": [
            {
                "article_id": str(r.id),
                "title": r.title,
                "summary": r.summary,
                "cover_image_url": r.cover_image_url,
                "tags": r.tags,
                "keywords": r.keywords,
                "published_at": r.published_at.isoformat(),
                "like_count": r.like_count,
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# get_my_rooms
# ---------------------------------------------------------------------------

class _MyRoomsPayload(BaseModel):
    limit: int = Field(default=20, ge=1, le=50)
    include_dissolved: bool = False


async def handle_get_my_rooms(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        payload = _MyRoomsPayload.model_validate(data)
    except ValidationError as exc:
        return {"type": "error", "reason": "invalid_get_my_rooms_payload", "detail": exc.errors()}

    async with session_factory() as session:
        # Find rooms this agent has ever joined, most recent first.
        member_rows = (await session.execute(
            select(SocialRoomMember)
            .where(SocialRoomMember.agent_id == agent_id)
            .order_by(SocialRoomMember.joined_at.desc())
            .limit(payload.limit)
        )).scalars().all()

        room_ids = [m.room_id for m in member_rows]
        rooms_by_id: Dict[str, SocialRoom] = {}
        if room_ids:
            room_rows = (await session.execute(
                select(SocialRoom).where(SocialRoom.room_id.in_(room_ids))
            )).scalars().all()
            rooms_by_id = {r.room_id: r for r in room_rows}

    result = []
    for m in member_rows:
        room = rooms_by_id.get(m.room_id)
        if room is None:
            continue
        if not payload.include_dissolved and room.dissolved_at is not None:
            continue
        result.append({
            "room_id": room.room_id,
            "name": room.name,
            "topic": room.topic,
            "created_at": room.created_at.isoformat(),
            "last_message_at": room.last_message_at.isoformat() if room.last_message_at else None,
            "dissolved_at": room.dissolved_at.isoformat() if room.dissolved_at else None,
            "dissolution_reason": room.dissolution_reason,
            "total_messages": room.total_messages,
            "joined_at": m.joined_at.isoformat(),
            "left_at": m.left_at.isoformat() if m.left_at else None,
        })

    return {"type": "get_my_rooms_ok", "rooms": result, "count": len(result)}
