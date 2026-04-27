import asyncio
import json
import secrets
from dataclasses import dataclass

from fastapi import WebSocket
from sqlalchemy import select

from app.crypto_tokens import constant_time_token_equals, sha256_hex
from app.models import Agent
from app.services.agent_event_log import record_agent_event


@dataclass(slots=True)
class WebSocketAuthResult:
    agent: Agent
    agent_id: str
    first_message_bytes: int


async def verify_agent_auth_payload(
    session_factory: object,
    *,
    agent_id: str,
    token: str,
    event_scope: str,
    byte_length: int,
) -> Agent | None:
    """Validate agent_id + raw token against DB. Record events on failure. No WebSocket I/O."""
    await record_agent_event(
        session_factory,
        event="ws_message_in",
        agent_id=agent_id,
        detail={
            "phase": "handshake",
            "message_type": "auth",
            "byte_length": byte_length,
            "scope": event_scope,
        },
    )

    async with session_factory() as session:
        result = await session.execute(select(Agent).where(Agent.agent_id == agent_id))
        agent = result.scalar_one_or_none()

    if agent is None:
        await record_agent_event(
            session_factory,
            event="auth_unknown_agent",
            agent_id=agent_id,
            detail={"scope": event_scope},
        )
        return None

    if agent.revoked_at is not None:
        await record_agent_event(
            session_factory,
            event="auth_revoked",
            agent_id=agent_id,
            detail={"scope": event_scope},
        )
        return None

    if not constant_time_token_equals(sha256_hex(token), agent.token_hash):
        await record_agent_event(
            session_factory,
            event="auth_invalid_token",
            agent_id=agent_id,
            detail={"scope": event_scope},
        )
        return None

    return agent


def verify_observe_shared_token(
    provided: str,
    expected: str,
) -> bool:
    """Constant-time compare for SOCIAL_OBSERVE_SHARED_TOKEN."""
    exp = (expected or "").strip()
    if not exp:
        return False
    return secrets.compare_digest((provided or "").strip(), exp)


async def authenticate_agent_websocket(
    websocket: WebSocket,
    *,
    session_factory: object,
    auth_timeout_seconds: int,
    max_message_bytes: int,
    event_scope: str,
) -> WebSocketAuthResult | None:
    """
    Perform shared agent WebSocket authentication for all channels.

    Returns a populated auth result on success, or None after closing the socket on failure.
    """
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=float(auth_timeout_seconds),
        )
    except asyncio.TimeoutError:
        await record_agent_event(
            session_factory,
            event="auth_timeout",
            agent_id=None,
            detail={"stage": "first_message", "scope": event_scope},
        )
        await websocket.close(code=4408, reason="auth_timeout")
        return None

    byte_len = len(raw.encode("utf-8"))
    if byte_len > max_message_bytes:
        await record_agent_event(
            session_factory,
            event="auth_first_message_too_large",
            agent_id=None,
            detail={"byte_length": byte_len, "scope": event_scope},
        )
        await websocket.close(code=1009, reason="too_large")
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await record_agent_event(
            session_factory,
            event="auth_invalid_json",
            agent_id=None,
            detail={"byte_length": byte_len, "scope": event_scope},
        )
        await websocket.send_text(json.dumps({"type": "auth_fail", "reason": "invalid_json"}))
        await websocket.close(code=1003, reason="invalid_json")
        return None

    if payload.get("type") != "auth":
        await record_agent_event(
            session_factory,
            event="auth_expected_type_auth",
            agent_id=None,
            detail={
                "byte_length": byte_len,
                "message_type": payload.get("type"),
                "scope": event_scope,
            },
        )
        await websocket.send_text(json.dumps({"type": "auth_fail", "reason": "expected_auth"}))
        await websocket.close(code=1003, reason="expected_auth")
        return None

    agent_id = payload.get("agent_id")
    token = payload.get("token")
    if not isinstance(agent_id, str) or not isinstance(token, str):
        await record_agent_event(
            session_factory,
            event="auth_invalid_payload",
            agent_id=agent_id if isinstance(agent_id, str) else None,
            detail={"byte_length": byte_len, "scope": event_scope},
        )
        await websocket.send_text(json.dumps({"type": "auth_fail", "reason": "invalid_payload"}))
        await websocket.close(code=1003, reason="invalid_payload")
        return None

    agent = await verify_agent_auth_payload(
        session_factory,
        agent_id=agent_id,
        token=token,
        event_scope=event_scope,
        byte_length=byte_len,
    )
    if agent is None:
        reason = "unknown_agent"
        code = 4401
        if await _agent_exists_revoked_or_bad(session_factory, agent_id, token):
            # Narrow failure reason for client (same as before)
            async with session_factory() as session:
                row = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
            if row is None:
                reason = "unknown_agent"
            elif row.revoked_at is not None:
                reason = "revoked"
                code = 4403
            else:
                reason = "invalid_token"
        await websocket.send_text(json.dumps({"type": "auth_fail", "reason": reason}))
        await websocket.close(code=code, reason=reason)
        return None

    return WebSocketAuthResult(
        agent=agent,
        agent_id=agent_id,
        first_message_bytes=byte_len,
    )


async def _agent_exists_revoked_or_bad(
    session_factory: object, agent_id: str, token: str
) -> bool:
    """True if we need to disambiguate auth_fail reason (agent row exists)."""
    async with session_factory() as session:
        row = await session.scalar(select(Agent).where(Agent.agent_id == agent_id))
    return row is not None
