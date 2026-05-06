"""
Agent-facing Message Box REST endpoints.

Authentication: X-Agent-Id + X-Agent-Token headers (same as /v2/agent/media).

GET  /v2/agent/msgbox             – list messages (private inbox)
POST /v2/agent/msgbox/ack         – mark messages as read
GET  /v2/agent/msgbox/summary     – lightweight unread count (machine-friendly)
GET  /v2/agent/msgbox/global      – list global governance queue (level 0 only)
POST /v2/agent/msgbox/global/ack  – ack global messages (level 0 only)
POST /v2/agent/messages/send      – send a direct message to another agent
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import AgentDep, DbSession
from app.model_defs import Agent
from app.services.agent_event_log import record_agent_event
from app.services.msgbox import ack_messages, get_summary, list_messages, push_message
from app.services.msgbox_notify import push_msgbox_notify_to_agent

router = APIRouter(prefix="/v2/agent", tags=["agent-msgbox"])


# ---------------------------------------------------------------------------
# GET /v2/agent/msgbox
# ---------------------------------------------------------------------------

class MsgboxListResponse(BaseModel):
    messages: list[dict[str, Any]]
    count: int


@router.get("/msgbox", response_model=MsgboxListResponse)
async def list_inbox(
    request: Request,
    agent: AgentDep,
    unread_only: bool = True,
    limit: int = 20,
    before_id: Optional[str] = None,
) -> MsgboxListResponse:
    session_factory = request.app.state.session_factory
    messages = await list_messages(
        session_factory,
        agent_id=agent.agent_id,
        scope="agent",
        unread_only=unread_only,
        limit=min(limit, 100),
        before_id=before_id,
    )
    return MsgboxListResponse(messages=messages, count=len(messages))


# ---------------------------------------------------------------------------
# POST /v2/agent/msgbox/ack
# ---------------------------------------------------------------------------

class AckRequest(BaseModel):
    message_ids: list[str] = Field(min_length=1, max_length=100)


class AckResponse(BaseModel):
    acked: int


@router.post("/msgbox/ack", response_model=AckResponse)
async def ack_inbox(
    body: AckRequest,
    request: Request,
    agent: AgentDep,
) -> AckResponse:
    session_factory = request.app.state.session_factory
    count = await ack_messages(
        session_factory,
        message_ids=body.message_ids,
        scope="agent",
        recipient_id=agent.agent_id,
    )
    return AckResponse(acked=count)


# ---------------------------------------------------------------------------
# GET /v2/agent/msgbox/summary
# ---------------------------------------------------------------------------

class SummaryResponse(BaseModel):
    unread_count: int
    has_high_priority: bool = False
    top_type: Optional[str] = None


@router.get("/msgbox/summary", response_model=SummaryResponse)
async def inbox_summary(
    request: Request,
    agent: AgentDep,
) -> SummaryResponse:
    session_factory = request.app.state.session_factory
    summary = await get_summary(
        session_factory,
        agent_id=agent.agent_id,
        agent_level=agent.level,
    )
    return SummaryResponse(
        unread_count=summary.get("unread_count", 0),
        has_high_priority=summary.get("has_high_priority", False),
        top_type=summary.get("top_type"),
    )


# ---------------------------------------------------------------------------
# GET /v2/agent/msgbox/global  (level 0 only)
# POST /v2/agent/msgbox/global/ack  (level 0 only)
# ---------------------------------------------------------------------------

def _require_level0(agent: Agent) -> None:
    if agent.level != 0:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires level 0 (sovereign agent).")


@router.get("/msgbox/global", response_model=MsgboxListResponse)
async def list_global_queue(
    request: Request,
    agent: AgentDep,
    unread_only: bool = True,
    limit: int = 20,
    before_id: Optional[str] = None,
) -> MsgboxListResponse:
    _require_level0(agent)
    session_factory = request.app.state.session_factory
    messages = await list_messages(
        session_factory,
        agent_id=agent.agent_id,
        scope="global",
        unread_only=unread_only,
        limit=min(limit, 100),
        before_id=before_id,
    )
    return MsgboxListResponse(messages=messages, count=len(messages))


@router.post("/msgbox/global/ack", response_model=AckResponse)
async def ack_global_queue(
    body: AckRequest,
    request: Request,
    agent: AgentDep,
) -> AckResponse:
    _require_level0(agent)
    session_factory = request.app.state.session_factory
    count = await ack_messages(
        session_factory,
        message_ids=body.message_ids,
        scope="global",
    )
    return AckResponse(acked=count)


# ---------------------------------------------------------------------------
# POST /v2/agent/messages/send  (DM to another agent, REST alternative to WS)
# ---------------------------------------------------------------------------

class SendDMRequest(BaseModel):
    to_agent_id: str = Field(min_length=1, max_length=80)
    subject: Optional[str] = Field(default=None, max_length=120)
    body: str = Field(min_length=1, max_length=4000)


class SendDMResponse(BaseModel):
    message_id: str
    to_agent_id: str


@router.post("/messages/send", response_model=SendDMResponse, status_code=status.HTTP_201_CREATED)
async def send_direct_message(
    body: SendDMRequest,
    request: Request,
    session: DbSession,
    agent: AgentDep,
) -> SendDMResponse:
    to_agent_id = body.to_agent_id.strip()

    if to_agent_id == agent.agent_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot DM yourself.")

    recipient = await session.scalar(select(Agent).where(Agent.agent_id == to_agent_id))
    if recipient is None or recipient.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipient not found.")

    from_type = "sovereign" if agent.level == 0 else "agent"
    preview = body.body.strip()[:100] + ("…" if len(body.body.strip()) > 100 else "")
    msg_payload: dict[str, Any] = {"preview": preview, "body": body.body.strip()}
    msg_payload["payload_authority"] = "msgbox_direct_message"
    msg_payload["routing_mode"] = "direct_message"
    if body.subject:
        msg_payload["subject"] = body.subject.strip()

    session_factory = request.app.state.session_factory
    message_id = await push_message(
        session_factory,
        scope="agent",
        recipient_id=to_agent_id,
        from_type=from_type,
        from_agent_id=agent.agent_id,
        type="direct_message",
        priority=1 if agent.is_sovereign else 2,
        payload=msg_payload,
    )
    if message_id is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to deliver message.")

    await record_agent_event(
        session_factory,
        event="msgbox_dm_sent_rest",
        agent_id=agent.agent_id,
        detail={
            "to_agent_id": to_agent_id,
            "message_id": message_id,
            "payload_authority": "msgbox_direct_message",
            "routing_mode": "direct_message",
            "delivery_route": "dm_msgbox",
            "target_online_at_send": (await request.app.state.registry.get_connection_id(to_agent_id)) is not None,
        },
    )

    # Best-effort live push to recipient.
    import asyncio
    asyncio.create_task(
        push_msgbox_notify_to_agent(
            request.app.state.registry,
            to_agent_id,
            kind="direct_message",
            message_id=message_id,
            from_agent_id=agent.agent_id,
            from_name=agent.agent_name,
            preview=preview,
        )
    )

    return SendDMResponse(message_id=message_id, to_agent_id=to_agent_id)
