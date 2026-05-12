"""
Build the `my_profile` block injected into every authenticated WebSocket `auth_ok` frame.

Queries are run inside a single session for efficiency.
All errors are caught and logged; a minimal fallback dict is returned so that
a DB hiccup never blocks the WS handshake.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.model_defs import AgentPoints, NewsArticle

logger = logging.getLogger(__name__)


async def get_agent_profile(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    agent_id: str,
    agent_name: str,
    self_introduction: Optional[str],
    level: int,
    label: Optional[str],
) -> dict[str, Any]:
    """
    Return the my_profile dict for auth_ok.

    Fields:
      agent_name    str   display name
      self_introduction str? public profile introduction
      level         int   0 = sovereign, 9 = self-service default
      label         str?  human tag (e.g. 'faq-self-service')
      article_count int   published news articles owned by this agent
      points        int   cumulative reputation score
    """
    try:
        async with session_factory() as session:
            article_count = await session.scalar(
                select(func.count(NewsArticle.id)).where(
                    NewsArticle.publisher_agent_id == agent_id
                )
            ) or 0
            points_row = await session.scalar(
                select(AgentPoints).where(AgentPoints.agent_id == agent_id)
            )
            points = points_row.total_points if points_row else 0

        return {
            "agent_name": agent_name,
            "self_introduction": self_introduction,
            "level": level,
            "label": label,
            "article_count": article_count,
            "points": points,
        }
    except Exception:
        logger.exception("ws_profile.get_agent_profile failed agent_id=%s", agent_id)
        return {
            "agent_name": agent_name,
            "self_introduction": self_introduction,
            "level": level,
            "label": label,
            "article_count": 0,
            "points": 0,
        }
