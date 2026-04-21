import asyncio
import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.crypto_tokens import constant_time_token_equals, sha256_hex
from app.models import Agent
from app.services.agent_event_log import record_agent_event
from app.services.permission_service import get_limit_value
from app.services.ws_mail_send import handle_send_mail_ws_message
from app.services.ws_news_delete import handle_delete_news_ws_message
from app.services.ws_news_publish import handle_publish_news_ws_message
from app.services.ws_news_update import handle_update_news_ws_message
from app.services.ws_skills_delete import handle_delete_skill_ws_message
from app.services.ws_skills_publish import handle_publish_skill_ws_message
from app.services.ws_skills_update import handle_update_skill_ws_message
from app.ws_registry import AgentConnectionRegistry


async def handle_agent_websocket(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    registry: AgentConnectionRegistry = websocket.app.state.registry
    session_factory = websocket.app.state.session_factory

    await websocket.accept()

    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=float(settings.agent_ws_auth_timeout_seconds),
        )
    except asyncio.TimeoutError:
        await record_agent_event(
            session_factory,
            event="auth_timeout",
            agent_id=None,
            detail={"stage": "first_message"},
        )
        await websocket.close(code=4408, reason="auth_timeout")
        return

    byte_len = len(raw.encode("utf-8"))
    if byte_len > settings.agent_ws_max_message_bytes:
        await record_agent_event(
            session_factory,
            event="auth_first_message_too_large",
            agent_id=None,
            detail={"byte_length": byte_len},
        )
        await websocket.close(code=1009, reason="too_large")
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await record_agent_event(
            session_factory,
            event="auth_invalid_json",
            agent_id=None,
            detail={"byte_length": byte_len},
        )
        await websocket.send_text(json.dumps({"type": "auth_fail", "reason": "invalid_json"}))
        await websocket.close(code=1003, reason="invalid_json")
        return

    if payload.get("type") != "auth":
        await record_agent_event(
            session_factory,
            event="auth_expected_type_auth",
            agent_id=None,
            detail={"byte_length": byte_len, "message_type": payload.get("type")},
        )
        await websocket.send_text(json.dumps({"type": "auth_fail", "reason": "expected_auth"}))
        await websocket.close(code=1003, reason="expected_auth")
        return

    agent_id = payload.get("agent_id")
    token = payload.get("token")
    if not isinstance(agent_id, str) or not isinstance(token, str):
        await record_agent_event(
            session_factory,
            event="auth_invalid_payload",
            agent_id=agent_id if isinstance(agent_id, str) else None,
            detail={"byte_length": byte_len},
        )
        await websocket.send_text(json.dumps({"type": "auth_fail", "reason": "invalid_payload"}))
        await websocket.close(code=1003, reason="invalid_payload")
        return

    await record_agent_event(
        session_factory,
        event="ws_message_in",
        agent_id=agent_id,
        detail={"phase": "handshake", "message_type": "auth", "byte_length": byte_len},
    )

    async with session_factory() as session:
        result = await session.execute(select(Agent).where(Agent.agent_id == agent_id))
        agent = result.scalar_one_or_none()

    if agent is None:
        await record_agent_event(
            session_factory,
            event="auth_unknown_agent",
            agent_id=agent_id,
            detail={},
        )
        await websocket.send_text(json.dumps({"type": "auth_fail", "reason": "unknown_agent"}))
        await websocket.close(code=4401, reason="unknown_agent")
        return

    if agent.revoked_at is not None:
        await record_agent_event(
            session_factory,
            event="auth_revoked",
            agent_id=agent_id,
            detail={},
        )
        await websocket.send_text(json.dumps({"type": "auth_fail", "reason": "revoked"}))
        await websocket.close(code=4403, reason="revoked")
        return

    if not constant_time_token_equals(sha256_hex(token), agent.token_hash):
        await record_agent_event(
            session_factory,
            event="auth_invalid_token",
            agent_id=agent_id,
            detail={},
        )
        await websocket.send_text(json.dumps({"type": "auth_fail", "reason": "invalid_token"}))
        await websocket.close(code=4401, reason="invalid_token")
        return

    connection_id = str(uuid.uuid4())

    previous = await registry.replace(agent_id, websocket, connection_id)
    if previous is not None and previous is not websocket:
        await record_agent_event(
            session_factory,
            event="ws_superseded",
            agent_id=agent_id,
            detail={"reason": "replaced_by_new_connection", "new_connection_id": connection_id},
        )
        try:
            await previous.send_text(
                json.dumps(
                    {
                        "type": "superseded",
                        "message": "Replaced by a new authenticated connection",
                        "agent_id": agent_id,
                    }
                )
            )
            await record_agent_event(
                session_factory,
                event="ws_message_out",
                agent_id=agent_id,
                connection_id=None,
                detail={"message_type": "superseded", "target": "previous_connection"},
            )
            await previous.close(code=4000, reason="superseded")
        except Exception:
            pass

    auth_ok_body = {
        "type": "auth_ok",
        "connection_id": connection_id,
        "agent_id": agent_id,
        "level": agent.level,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
    await websocket.send_text(json.dumps(auth_ok_body))
    await record_agent_event(
        session_factory,
        event="ws_message_out",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={"message_type": "auth_ok"},
    )

    await record_agent_event(
        session_factory,
        event="ws_connected",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={"level": agent.level},
    )

    async with session_factory() as _rl_session:
        db_rate_limit = await get_limit_value(_rl_session, "ws", "rate_limit_per_minute")
    rate_limit = db_rate_limit if db_rate_limit is not None else settings.agent_ws_rate_limit_per_minute
    rate_window: deque[float] = deque(maxlen=rate_limit if rate_limit > 0 else None)

    disconnect_reason: Optional[str] = None
    try:
        while True:
            msg = await websocket.receive_text()
            msg_bytes = len(msg.encode("utf-8"))

            # Rate limiting: sliding 60-second window.
            if rate_limit > 0:
                now = time.monotonic()
                rate_window.append(now)
                if len(rate_window) == rate_limit and (now - rate_window[0]) < 60.0:
                    await websocket.send_text(
                        json.dumps({"type": "error", "reason": "rate_limit_exceeded"})
                    )
                    await record_agent_event(
                        session_factory,
                        event="ws_rate_limit_exceeded",
                        agent_id=agent_id,
                        connection_id=connection_id,
                        detail={"rate_limit_per_minute": rate_limit},
                    )
                    await websocket.close(code=4029, reason="rate_limit_exceeded")
                    disconnect_reason = "rate_limit_exceeded"
                    break

            if msg_bytes > settings.agent_ws_max_message_bytes:
                await record_agent_event(
                    session_factory,
                    event="ws_message_in_too_large",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"byte_length": msg_bytes},
                )
                await websocket.close(code=1009, reason="too_large")
                disconnect_reason = "message_too_large"
                break
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                await record_agent_event(
                    session_factory,
                    event="ws_message_in",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"phase": "data", "parse": "invalid_json", "byte_length": msg_bytes},
                )
                out = json.dumps({"type": "error", "reason": "invalid_json"})
                await websocket.send_text(out)
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": "error", "reason": "invalid_json"},
                )
                continue
            msg_type = data.get("type")
            await record_agent_event(
                session_factory,
                event="ws_message_in",
                agent_id=agent_id,
                connection_id=connection_id,
                detail={
                    "phase": "data",
                    "message_type": msg_type,
                    "byte_length": msg_bytes,
                },
            )
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": "pong"},
                )
            elif msg_type == "publish_news":
                out = await handle_publish_news_ws_message(
                    news_markdown_root=settings.news_markdown_root,
                    session_factory=session_factory,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "update_news":
                out = await handle_update_news_ws_message(
                    news_markdown_root=settings.news_markdown_root,
                    session_factory=session_factory,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "delete_news":
                out = await handle_delete_news_ws_message(
                    session_factory=session_factory,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "send_mail":
                out = await handle_send_mail_ws_message(
                    smtp_service=getattr(websocket.app.state, "smtp_service", None),
                    session_factory=session_factory,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    agent_level=agent.level,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "publish_skill":
                out = await handle_publish_skill_ws_message(
                    session_factory=session_factory,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "update_skill":
                out = await handle_update_skill_ws_message(
                    session_factory=session_factory,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "delete_skill":
                out = await handle_delete_skill_ws_message(
                    session_factory=session_factory,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "command_result":
                request_id = data.get("request_id")
                if not isinstance(request_id, str) or not request_id:
                    await websocket.send_text(
                        json.dumps({"type": "error", "reason": "invalid_command_result"})
                    )
                    await record_agent_event(
                        session_factory,
                        event="ws_message_out",
                        agent_id=agent_id,
                        connection_id=connection_id,
                        detail={"message_type": "error", "reason": "invalid_command_result"},
                    )
                    continue
                delivered = await registry.resolve_command_result(agent_id, request_id, data)
                await record_agent_event(
                    session_factory,
                    event="ws_command_result_received",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"request_id": request_id, "delivered": delivered},
                )
                if not delivered:
                    await websocket.send_text(
                        json.dumps({"type": "error", "reason": "unknown_request_id"})
                    )
                    await record_agent_event(
                        session_factory,
                        event="ws_message_out",
                        agent_id=agent_id,
                        connection_id=connection_id,
                        detail={"message_type": "error", "reason": "unknown_request_id"},
                    )
            else:
                await websocket.send_text(json.dumps({"type": "error", "reason": "unknown_type"}))
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": "error", "reason": "unknown_type"},
                )
    except WebSocketDisconnect:
        disconnect_reason = "client_disconnect"
    finally:
        if disconnect_reason is not None:
            await record_agent_event(
                session_factory,
                event="ws_disconnected",
                agent_id=agent_id,
                connection_id=connection_id,
                detail={"reason": disconnect_reason},
            )
        await registry.remove_if_current(agent_id, websocket)
