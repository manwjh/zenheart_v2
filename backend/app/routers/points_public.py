"""Public read-only endpoints for agent reputation points.

GET /v2/points/leaderboard          — top agents ranked by total_points
GET /v2/points/agents/{agent_id}    — single agent's points
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.deps import DbSession
from app.model_defs import Agent, AgentPoints
from app.schemas import AgentPointsResponse, LeaderboardResponse, LeaderboardRow

router = APIRouter(prefix="/v2/points", tags=["points"])

_LEADERBOARD_MAX = 100


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    session: DbSession,
    limit: int = 20,
) -> LeaderboardResponse:
    """Return the top *limit* agents sorted by total reputation points."""
    limit = max(1, min(limit, _LEADERBOARD_MAX))

    AgentAlias = aliased(Agent)
    rows = (
        await session.execute(
            select(AgentPoints, AgentAlias.agent_name)
            .join(AgentAlias, AgentAlias.agent_id == AgentPoints.agent_id, isouter=True)
            .where(AgentAlias.revoked_at.is_(None))
            .order_by(AgentPoints.total_points.desc())
            .limit(limit)
        )
    ).all()

    items = [
        LeaderboardRow(
            rank=i + 1,
            agent_id=ap.agent_id,
            agent_name=name,
            total_points=ap.total_points,
        )
        for i, (ap, name) in enumerate(rows)
    ]
    return LeaderboardResponse(items=items)


@router.get("/agents/{agent_id}", response_model=AgentPointsResponse)
async def get_agent_points(
    agent_id: str,
    session: DbSession,
) -> AgentPointsResponse:
    """Return reputation points for a single agent."""
    ap = await session.scalar(
        select(AgentPoints).where(AgentPoints.agent_id == agent_id)
    )
    if ap is None:
        raise HTTPException(status_code=404, detail="Agent not found or has no points yet")

    agent_name: str | None = await session.scalar(
        select(Agent.agent_name).where(
            Agent.agent_id == agent_id,
            Agent.revoked_at.is_(None),
        )
    )
    return AgentPointsResponse(
        agent_id=agent_id,
        agent_name=agent_name,
        total_points=ap.total_points,
    )
