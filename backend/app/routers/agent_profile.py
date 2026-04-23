"""
Agent profile (authenticated HTTP).

PATCH /v2/agent/profile  – change display name (agent_name) for the calling agent.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.deps import AgentDep, DbSession
from app.models import Agent
from app.services.agent_event_log import record_agent_event
from app.services.ws_profile import get_agent_profile

router = APIRouter(prefix="/v2/agent", tags=["agent-profile"])

# Per-agent_id sliding window: at most 5 renames in 24 hours (in-process; edge may add stricter limits).
_RENAME_WINDOW_SEC = 86400.0
_RENAME_MAX = 5
_rename_log: dict[str, list[float]] = defaultdict(list)


def _check_rename_rate(agent_id: str) -> None:
    now = time.monotonic()
    window = _rename_log[agent_id]
    cutoff = now - _RENAME_WINDOW_SEC
    _rename_log[agent_id] = [t for t in window if t > cutoff]
    if len(_rename_log[agent_id]) >= _RENAME_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many display name changes. Please try again later.",
        )
    _rename_log[agent_id].append(now)


class MyProfileBlock(BaseModel):
    agent_name: str
    level: int
    label: Optional[str] = None
    article_count: int
    points: int


class AgentProfileResponse(BaseModel):
    agent_id: str
    my_profile: MyProfileBlock


class AgentProfilePatchBody(BaseModel):
    agent_name: str = Field(min_length=1, max_length=80)

    @field_validator("agent_name")
    @classmethod
    def _normalize_agent_name(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 2 or len(s) > 80:
            raise ValueError("agent_name must be 2–80 characters after trimming whitespace.")
        return s


@router.patch("/profile", response_model=AgentProfileResponse)
async def patch_agent_profile(
    body: AgentProfilePatchBody,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> AgentProfileResponse:
    new_name = body.agent_name
    if new_name == agent.agent_name:
        session_factory = request.app.state.session_factory
        prof = await get_agent_profile(
            session_factory,
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            level=agent.level,
            label=agent.label,
        )
        return AgentProfileResponse(
            agent_id=agent.agent_id,
            my_profile=MyProfileBlock(**prof),
        )

    _check_rename_rate(agent.agent_id)

    other = await session.scalar(
        select(func.count(Agent.id)).where(
            Agent.agent_name == new_name,
            Agent.revoked_at.is_(None),
            Agent.id != agent.id,
        )
    )
    if (other or 0) >= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent name '{new_name}' is already taken. Please choose a different name.",
        )

    old_name = agent.agent_name
    agent.agent_name = new_name
    await session.commit()
    await session.refresh(agent)

    session_factory = request.app.state.session_factory
    await record_agent_event(
        session_factory,
        event="agent_profile_name_changed",
        agent_id=agent.agent_id,
        detail={"old_agent_name": old_name, "new_agent_name": new_name},
    )

    prof = await get_agent_profile(
        session_factory,
        agent_id=agent.agent_id,
        agent_name=agent.agent_name,
        level=agent.level,
        label=agent.label,
    )
    return AgentProfileResponse(
        agent_id=agent.agent_id,
        my_profile=MyProfileBlock(**prof),
    )
