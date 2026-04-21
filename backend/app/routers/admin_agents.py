from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.crypto_tokens import generate_agent_id, generate_token, sha256_hex
from app.deps import DbSession, admin_key_guard
from app.models import Agent, AgentEventLog
from app.services.agent_event_log import record_agent_event
from app.schemas import (
    AdminAgentCredentialResponse,
    AgentPublicResponse,
    CreateAgentRequest,
    CreateAgentResponse,
    RevokeAgentResponse,
    RotateTokenResponse,
    AgentEventLogRow,
    AgentConnectionStatusResponse,
    DispatchAgentCommandRequest,
    DispatchAgentCommandResponse,
)

router = APIRouter(
    prefix="/v2/admin",
    tags=["admin"],
    dependencies=[Depends(admin_key_guard)],
)


async def _get_agent_or_404(session: DbSession, agent_id: str) -> Agent:
    result = await session.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent_id")
    return agent


@router.post("/agents", response_model=CreateAgentResponse)
async def create_agent(body: CreateAgentRequest, session: DbSession) -> CreateAgentResponse:
    agent_id = generate_agent_id()
    token = generate_token()
    token_hash = sha256_hex(token)
    agent = Agent(
        agent_id=agent_id,
        agent_name=body.agent_name.strip(),
        email=str(body.email),
        level=body.level,
        token_hash=token_hash,
        label=body.label,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return CreateAgentResponse(
        agent_id=agent.agent_id,
        agent_name=agent.agent_name,
        email=agent.email,
        level=agent.level,
        token=token,
        token_hash=agent.token_hash,
        label=agent.label,
        created_at=agent.created_at,
    )


@router.get("/agents", response_model=list[AgentPublicResponse])
async def list_agents(session: DbSession) -> list[AgentPublicResponse]:
    result = await session.execute(select(Agent).order_by(Agent.created_at.desc()))
    agents = result.scalars().all()
    return [
        AgentPublicResponse(
            agent_id=a.agent_id,
            agent_name=a.agent_name,
            email=a.email,
            level=a.level,
            label=a.label,
            revoked_at=a.revoked_at,
            created_at=a.created_at,
        )
        for a in agents
    ]


@router.get("/agents/{agent_id}", response_model=AdminAgentCredentialResponse)
async def get_agent_credentials(agent_id: str, session: DbSession) -> AdminAgentCredentialResponse:
    agent = await _get_agent_or_404(session, agent_id)
    return AdminAgentCredentialResponse(
        agent_id=agent.agent_id,
        agent_name=agent.agent_name,
        email=agent.email,
        level=agent.level,
        label=agent.label,
        revoked_at=agent.revoked_at,
        created_at=agent.created_at,
        token_hash=agent.token_hash,
    )


@router.post("/agents/{agent_id}/revoke", response_model=RevokeAgentResponse)
async def revoke_agent(agent_id: str, session: DbSession, request: Request) -> RevokeAgentResponse:
    agent = await _get_agent_or_404(session, agent_id)
    now = datetime.now(timezone.utc)
    agent.revoked_at = now
    await session.commit()
    registry = request.app.state.registry
    await registry.force_disconnect(
        agent_id,
        {"type": "session_closed", "reason": "revoked"},
        4403,
        "revoked",
    )
    session_factory = request.app.state.session_factory
    await record_agent_event(
        session_factory,
        event="admin_force_disconnect",
        agent_id=agent_id,
        detail={"reason": "revoked"},
    )
    return RevokeAgentResponse(agent_id=agent.agent_id, revoked_at=now)


@router.post("/agents/{agent_id}/rotate-token", response_model=RotateTokenResponse)
async def rotate_agent_token(agent_id: str, session: DbSession, request: Request) -> RotateTokenResponse:
    agent = await _get_agent_or_404(session, agent_id)
    token = generate_token()
    token_hash = sha256_hex(token)
    agent.token_hash = token_hash
    agent.revoked_at = None
    await session.commit()
    registry = request.app.state.registry
    await registry.force_disconnect(
        agent_id,
        {"type": "session_closed", "reason": "token_rotated"},
        4001,
        "token_rotated",
    )
    session_factory = request.app.state.session_factory
    await record_agent_event(
        session_factory,
        event="admin_force_disconnect",
        agent_id=agent_id,
        detail={"reason": "token_rotated"},
    )
    return RotateTokenResponse(agent_id=agent.agent_id, token=token, token_hash=token_hash)


@router.get("/agents/{agent_id}/event-logs", response_model=list[AgentEventLogRow])
async def list_agent_event_logs(
    agent_id: str,
    session: DbSession,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[AgentEventLogRow]:
    await _get_agent_or_404(session, agent_id)
    result = await session.execute(
        select(AgentEventLog)
        .where(AgentEventLog.agent_id == agent_id)
        .order_by(AgentEventLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    return [
        AgentEventLogRow(
            id=r.id,
            agent_id=r.agent_id,
            connection_id=r.connection_id,
            event=r.event,
            detail=r.detail,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/agents/{agent_id}/connection", response_model=AgentConnectionStatusResponse)
async def get_agent_connection_status(
    agent_id: str, session: DbSession, request: Request
) -> AgentConnectionStatusResponse:
    await _get_agent_or_404(session, agent_id)
    registry = request.app.state.registry
    connection_id = await registry.get_connection_id(agent_id)
    return AgentConnectionStatusResponse(
        agent_id=agent_id,
        connected=connection_id is not None,
        connection_id=connection_id,
    )


@router.post("/agents/{agent_id}/commands", response_model=DispatchAgentCommandResponse)
async def dispatch_agent_command(
    agent_id: str,
    body: DispatchAgentCommandRequest,
    session: DbSession,
    request: Request,
) -> DispatchAgentCommandResponse:
    await _get_agent_or_404(session, agent_id)
    registry = request.app.state.registry
    session_factory = request.app.state.session_factory
    request_id = str(uuid.uuid4())
    command_payload = {
        "type": "command",
        "request_id": request_id,
        "command": body.command,
        "args": body.args,
    }
    await record_agent_event(
        session_factory,
        event="admin_command_dispatched",
        agent_id=agent_id,
        detail={
            "request_id": request_id,
            "command": body.command,
            "args_keys": sorted(list(body.args.keys())),
            "timeout_seconds": body.timeout_seconds,
        },
    )
    try:
        result = await registry.dispatch_command_and_wait(
            agent_id=agent_id,
            request_id=request_id,
            message=command_payload,
            timeout_seconds=float(body.timeout_seconds),
        )
    except RuntimeError as exc:
        reason = str(exc)
        await record_agent_event(
            session_factory,
            event="admin_command_failed",
            agent_id=agent_id,
            detail={"request_id": request_id, "reason": reason},
        )
        if reason == "agent_not_connected":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Agent is not connected",
            )
        if reason == "command_timeout":
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Timed out waiting for command_result",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Command dispatch failed: {reason}",
        )

    await record_agent_event(
        session_factory,
        event="admin_command_completed",
        agent_id=agent_id,
        detail={"request_id": request_id, "command": body.command},
    )
    return DispatchAgentCommandResponse(
        agent_id=agent_id,
        request_id=request_id,
        accepted=True,
        result=result,
    )
