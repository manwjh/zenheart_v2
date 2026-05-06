"""
Public (unauthenticated) endpoints under /v2/agents/* and /v2/content/*.

GET  /v2/agents                     – public agent directory (active agents)
GET  /v2/agents/by-name             – public profile by exact agent_name (query param)
GET  /v2/agents/{agent_id}          – public profile of a single agent
POST /v2/agents/{agent_id}/contact  – human visitor sends a DM to an agent
POST /v2/content/report             – report content (article / comment / room_message)

Contact and report endpoints are IP-rate-limited at the application level.
Heavy-traffic sites should add an upstream rate limiter.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.deps import DbSession
from app.model_defs import Agent, AgentEventLog, AgentPoints, NewsArticle
from app.services.agent_event_log import record_agent_event
from app.services.msgbox import push_message
from app.services.msgbox_notify import push_msgbox_notify_to_agent
from app.services.sovereign_notify import push_msgbox_notify_to_sovereigns

router = APIRouter(tags=["msgbox-public"])

# ---------------------------------------------------------------------------
# Simple in-memory IP rate limiter (sliding window, per-endpoint key)
# 10 requests per IP per 60 seconds
# ---------------------------------------------------------------------------

_RATE_LIMIT = 10
_RATE_WINDOW = 60.0

_timestamps: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    window = _timestamps[key]
    cutoff = now - _RATE_WINDOW
    _timestamps[key] = [t for t in window if t > cutoff]
    if len(_timestamps[key]) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
        )
    _timestamps[key].append(now)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# GET /v2/agents  — public agent directory
# GET /v2/agents/by-name  — single agent by exact display name
# GET /v2/agents/{agent_id}  — single agent public profile
# ---------------------------------------------------------------------------

class AgentPublicProfile(BaseModel):
    agent_id: str
    agent_name: str
    level: int
    label: Optional[str]
    registered_at: datetime
    last_seen_at: Optional[datetime]
    article_count: int
    points: int


class AgentDirectoryPublicResponse(BaseModel):
    total: int
    agents: list[AgentPublicProfile]


def _last_seen_subquery():
    visit_events = ("ws_connected", "a2a_ws_connected")
    return (
        select(
            AgentEventLog.agent_id,
            func.max(AgentEventLog.created_at).label("last_seen_at"),
        )
        .where(AgentEventLog.event.in_(visit_events))
        .group_by(AgentEventLog.agent_id)
        .subquery()
    )


_VISIT_EVENTS = ("ws_connected", "a2a_ws_connected")


async def _public_profile_for_agent(session: DbSession, agent: Agent) -> AgentPublicProfile:
    """Build the same payload as GET /v2/agents/{agent_id} (no extra joins)."""
    agent_id = agent.agent_id
    last_seen_at = await session.scalar(
        select(func.max(AgentEventLog.created_at)).where(
            AgentEventLog.agent_id == agent_id,
            AgentEventLog.event.in_(_VISIT_EVENTS),
        )
    )
    total_points = await session.scalar(
        select(func.coalesce(AgentPoints.total_points, 0)).where(
            AgentPoints.agent_id == agent_id,
        )
    )
    article_count = await session.scalar(
        select(func.count(NewsArticle.id)).where(
            NewsArticle.publisher_agent_id == agent_id,
        )
    )
    return AgentPublicProfile(
        agent_id=agent.agent_id,
        agent_name=agent.agent_name,
        level=agent.level,
        label=agent.label,
        registered_at=agent.created_at,
        last_seen_at=last_seen_at,
        article_count=int(article_count or 0),
        points=int(total_points or 0),
    )


@router.get("/v2/agents", response_model=AgentDirectoryPublicResponse)
async def list_agents_public(session: DbSession) -> AgentDirectoryPublicResponse:
    """Public directory of all active agents, sorted by points descending."""
    last_seen_subq = _last_seen_subquery()
    rows = (
        await session.execute(
            select(
                Agent.agent_id,
                Agent.agent_name,
                Agent.level,
                Agent.label,
                Agent.created_at.label("registered_at"),
                last_seen_subq.c.last_seen_at,
                func.coalesce(AgentPoints.total_points, 0).label("total_points"),
                func.count(NewsArticle.id).label("article_count"),
            )
            .outerjoin(last_seen_subq, last_seen_subq.c.agent_id == Agent.agent_id)
            .outerjoin(AgentPoints, AgentPoints.agent_id == Agent.agent_id)
            .outerjoin(NewsArticle, NewsArticle.publisher_agent_id == Agent.agent_id)
            .where(Agent.revoked_at.is_(None))
            .group_by(
                Agent.agent_id, Agent.agent_name, Agent.level, Agent.label,
                Agent.created_at, last_seen_subq.c.last_seen_at, AgentPoints.total_points,
            )
            .order_by(
                func.coalesce(AgentPoints.total_points, 0).desc(),
                Agent.created_at.asc(),
            )
        )
    ).all()

    agents = [
        AgentPublicProfile(
            agent_id=row.agent_id,
            agent_name=row.agent_name,
            level=row.level,
            label=row.label,
            registered_at=row.registered_at,
            last_seen_at=row.last_seen_at,
            article_count=int(row.article_count),
            points=int(row.total_points),
        )
        for row in rows
    ]
    return AgentDirectoryPublicResponse(total=len(agents), agents=agents)


@router.get("/v2/agents/by-name", response_model=AgentPublicProfile)
async def get_agent_profile_by_agent_name(
    session: DbSession,
    agent_name: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description="Exact stored display name after trimming whitespace; match is case-sensitive.",
    ),
) -> AgentPublicProfile:
    """Public profile of a single active agent identified by exact ``agent_name``."""
    name = agent_name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="agent_name must not be empty.",
        )
    agent = await session.scalar(
        select(Agent).where(Agent.agent_name == name, Agent.revoked_at.is_(None))
    )
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return await _public_profile_for_agent(session, agent)


@router.get("/v2/agents/{agent_id}", response_model=AgentPublicProfile)
async def get_agent_profile_public(agent_id: str, session: DbSession) -> AgentPublicProfile:
    """Public profile of a single active agent."""
    agent = await session.scalar(
        select(Agent).where(Agent.agent_id == agent_id, Agent.revoked_at.is_(None))
    )
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    return await _public_profile_for_agent(session, agent)


# ---------------------------------------------------------------------------
# POST /v2/agents/{agent_id}/contact
# ---------------------------------------------------------------------------

class ContactRequest(BaseModel):
    from_name: str = Field(min_length=1, max_length=80)
    from_email: Optional[EmailStr] = None
    subject: Optional[str] = Field(default=None, max_length=120)
    body: str = Field(min_length=10, max_length=4000)


class ContactResponse(BaseModel):
    delivered: bool
    message: str


@router.post(
    "/v2/agents/{agent_id}/contact",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def contact_agent(
    agent_id: str,
    body: ContactRequest,
    request: Request,
    session: DbSession,
) -> ContactResponse:
    ip = _client_ip(request)
    _check_rate_limit(f"contact:{ip}")

    recipient = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
    if recipient is None or recipient.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    preview = body.body.strip()[:100] + ("…" if len(body.body.strip()) > 100 else "")
    msg_payload = {
        "preview": preview,
        "body": body.body.strip(),
        "from_email": str(body.from_email) if body.from_email else None,
    }
    if body.subject:
        msg_payload["subject"] = body.subject.strip()

    session_factory = request.app.state.session_factory
    message_id = await push_message(
        session_factory,
        scope="agent",
        recipient_id=agent_id,
        from_type="anonymous",
        visitor_from_name=body.from_name.strip() if body.from_name else None,
        type="direct_message",
        priority=2,
        payload=msg_payload,
    )
    if message_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deliver message.",
        )

    stripped_body = body.body.strip()
    await record_agent_event(
        session_factory,
        event="msgbox_contact_submitted_public",
        agent_id=None,
        detail={
            "to_agent_id": agent_id,
            "message_id": message_id,
            "client_ip": ip,
            "from_name": body.from_name.strip() if body.from_name else None,
            "body_length": len(stripped_body),
        },
    )

    # Best-effort live push.
    registry = request.app.state.registry
    asyncio.create_task(
        push_msgbox_notify_to_agent(
            registry,
            agent_id,
            kind="direct_message",
            message_id=message_id,
            from_name=body.from_name.strip() if body.from_name else None,
            preview=preview,
            extra={"from_type": "anonymous"},
        )
    )

    return ContactResponse(delivered=True, message="Message delivered to agent's inbox.")


# ---------------------------------------------------------------------------
# POST /v2/content/report
# ---------------------------------------------------------------------------

_VALID_RESOURCE_TYPES = {"article", "comment", "room_message"}


class ReportRequest(BaseModel):
    resource_type: str = Field(min_length=1, max_length=40)
    resource_id: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=10, max_length=500)
    from_name: Optional[str] = Field(default=None, max_length=80)


class ReportResponse(BaseModel):
    received: bool
    message: str


@router.post(
    "/v2/content/report",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def report_content(
    body: ReportRequest,
    request: Request,
) -> ReportResponse:
    ip = _client_ip(request)
    _check_rate_limit(f"report:{ip}")

    if body.resource_type not in _VALID_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"resource_type must be one of: {', '.join(sorted(_VALID_RESOURCE_TYPES))}",
        )

    msg_type = f"report:{body.resource_type}"
    session_factory = request.app.state.session_factory
    message_id = await push_message(
        session_factory,
        scope="global",
        from_type="anonymous",
        visitor_from_name=body.from_name,
        type=msg_type,
        priority=1,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        payload={"reason": body.reason.strip()},
    )
    if message_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit report.",
        )

    await record_agent_event(
        session_factory,
        event="content_report_submitted_public",
        agent_id=None,
        detail={
            "resource_type": body.resource_type,
            "resource_id": body.resource_id,
            "message_id": message_id,
            "client_ip": ip,
            "reason_length": len(body.reason.strip()),
            "reporter_from_name": body.from_name.strip() if body.from_name else None,
        },
    )

    # Best-effort live push to sovereign agents via shared helper.
    asyncio.create_task(
        push_msgbox_notify_to_sovereigns(
            request.app.state.session_factory,
            request.app.state.registry,
            message_id=message_id,
            kind=msg_type,
            extra={
                "resource_type": body.resource_type,
                "resource_id": body.resource_id,
                "priority": 1,
            },
        )
    )

    return ReportResponse(received=True, message="Report received. Thank you.")
