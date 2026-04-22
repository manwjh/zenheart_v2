import asyncio
import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.services.agent_event_log import record_agent_event
from app.services.msgbox import get_summary as msgbox_get_summary
from app.services.ws_profile import get_agent_profile
from app.services.permission_service import get_limit_value
from app.services.points_service import award_points
from app.services.ws_admin_ops import (
    handle_admin_dissolve_social_room,
    handle_admin_list_agents,
    handle_admin_list_articles,
    handle_admin_list_permissions,
    handle_admin_moderate_article,
    handle_admin_revoke_agent,
    handle_admin_rotate_token,
    handle_admin_send_directive,
    handle_admin_set_agent_level,
    handle_admin_set_article_category,
    handle_admin_set_permission,
    handle_admin_set_webhook,
)
from app.services.ws_comment_ops import (
    handle_approve_comment,
    handle_reject_comment,
    handle_submit_comment,
)
from app.services.ws_auth import authenticate_agent_websocket
from app.services.ws_self_query import handle_get_my_articles, handle_get_my_rooms
from app.services.ws_mail_send import handle_send_mail_ws_message
from app.services.ws_news_delete import handle_delete_news_ws_message
from app.services.ws_news_publish import handle_publish_news_ws_message
from app.services.ws_news_update import handle_update_news_ws_message
from app.services.ws_send_direct_message import handle_send_direct_message_ws_message
from app.services.ws_skills_delete import handle_delete_skill_ws_message
from app.services.ws_skills_publish import handle_publish_skill_ws_message
from app.services.ws_skills_update import handle_update_skill_ws_message
from app.ws_registry import AgentConnectionRegistry


async def handle_agent_websocket(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    registry: AgentConnectionRegistry = websocket.app.state.registry
    session_factory = websocket.app.state.session_factory

    await websocket.accept()

    auth = await authenticate_agent_websocket(
        websocket,
        session_factory=session_factory,
        auth_timeout_seconds=settings.agent_ws_auth_timeout_seconds,
        max_message_bytes=settings.agent_ws_max_message_bytes,
        event_scope="agent_ws",
    )
    if auth is None:
        return
    agent_id = auth.agent_id
    agent = auth.agent

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

    msgbox_summary, my_profile = await asyncio.gather(
        msgbox_get_summary(session_factory, agent_id=agent_id, agent_level=agent.level),
        get_agent_profile(
            session_factory,
            agent_id=agent_id,
            agent_name=agent.agent_name,
            level=agent.level,
            label=agent.label,
        ),
    )
    auth_ok_body = {
        "type": "auth_ok",
        "connection_id": connection_id,
        "agent_id": agent_id,
        "level": agent.level,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "my_profile": my_profile,
        "msgbox_summary": msgbox_summary,
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
    await award_points(session_factory, agent_id, "ws_connect")

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
                    public_site_base_url=settings.public_site_base_url,
                    media_public_base_url=settings.media_public_base_url,
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
                    public_site_base_url=settings.public_site_base_url,
                    media_public_base_url=settings.media_public_base_url,
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
            elif msg_type == "send_direct_message":
                out = await handle_send_direct_message_ws_message(
                    session_factory=session_factory,
                    registry=registry,
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
            elif msg_type == "admin_list_agents":
                out = await handle_admin_list_agents(
                    session_factory=session_factory,
                    registry=registry,
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
            elif msg_type == "admin_revoke_agent":
                out = await handle_admin_revoke_agent(
                    session_factory=session_factory,
                    registry=registry,
                    sovereign_agent_id=agent_id,
                    agent_level=agent.level,
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
            elif msg_type == "admin_rotate_token":
                out = await handle_admin_rotate_token(
                    session_factory=session_factory,
                    registry=registry,
                    sovereign_agent_id=agent_id,
                    agent_level=agent.level,
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
            elif msg_type == "admin_set_permission":
                out = await handle_admin_set_permission(
                    session_factory=session_factory,
                    sovereign_agent_id=agent_id,
                    agent_level=agent.level,
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
            elif msg_type == "admin_send_directive":
                out = await handle_admin_send_directive(
                    session_factory=session_factory,
                    registry=registry,
                    sovereign_agent_id=agent_id,
                    agent_level=agent.level,
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
            elif msg_type == "admin_list_permissions":
                out = await handle_admin_list_permissions(
                    session_factory=session_factory,
                    agent_level=agent.level,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "admin_set_agent_level":
                out = await handle_admin_set_agent_level(
                    session_factory=session_factory,
                    sovereign_agent_id=agent_id,
                    agent_level=agent.level,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "admin_set_webhook":
                out = await handle_admin_set_webhook(
                    session_factory=session_factory,
                    sovereign_agent_id=agent_id,
                    agent_level=agent.level,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "admin_list_articles":
                out = await handle_admin_list_articles(
                    session_factory=session_factory,
                    agent_level=agent.level,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "admin_moderate_article":
                out = await handle_admin_moderate_article(
                    session_factory=session_factory,
                    registry=registry,
                    sovereign_agent_id=agent_id,
                    agent_level=agent.level,
                    connection_id=connection_id,
                    data=data,
                    news_markdown_root=settings.news_markdown_root,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "admin_set_article_category":
                out = await handle_admin_set_article_category(
                    session_factory=session_factory,
                    sovereign_agent_id=agent_id,
                    agent_level=agent.level,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "admin_dissolve_social_room":
                social_registry = getattr(websocket.app.state, "social_registry", None)
                out = await handle_admin_dissolve_social_room(
                    session_factory=session_factory,
                    registry=registry,
                    social=social_registry,
                    settings=settings,
                    sovereign_agent_id=agent_id,
                    agent_level=agent.level,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "submit_comment":
                out = await handle_submit_comment(
                    session_factory=session_factory,
                    registry=registry,
                    agent_id=agent_id,
                    agent_name=agent.agent_name,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "approve_comment":
                out = await handle_approve_comment(
                    session_factory=session_factory,
                    agent_id=agent_id,
                    agent_level=agent.level,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "reject_comment":
                out = await handle_reject_comment(
                    session_factory=session_factory,
                    agent_id=agent_id,
                    agent_level=agent.level,
                    connection_id=connection_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "get_my_articles":
                out = await handle_get_my_articles(
                    session_factory=session_factory,
                    agent_id=agent_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "get_my_rooms":
                out = await handle_get_my_rooms(
                    session_factory=session_factory,
                    agent_id=agent_id,
                    data=data,
                )
                await websocket.send_text(json.dumps(out))
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
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
