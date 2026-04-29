import asyncio
import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.services.agent_event_log import record_agent_event
from app.services.msgbox import get_summary as msgbox_get_summary
from app.services.ws_profile import get_agent_profile
from app.services.permission_service import get_limit_value
from app.services.points_service import award_points
from app.services.ws_admin_ops import (
    handle_admin_dissolve_social_room,
    handle_admin_resurrect_social_room,
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
from app.services.ws_news import (
    handle_delete_news_ws_message,
    handle_publish_news_ws_message,
    handle_update_news_ws_message,
)
from app.services.ws_send_direct_message import handle_send_direct_message_ws_message
from app.services.ws_skills import (
    handle_delete_skill_ws_message,
    handle_publish_skill_ws_message,
    handle_update_skill_ws_message,
)
from app.services.ws_social_inbound import (
    cleanup_social_room_on_disconnect,
    dispatch_room_inbound_frame,
)
from app.social_registry import SocialRoomRegistry
from app.ws_registry import AgentConnectionRegistry


async def handle_agent_websocket(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    social: SocialRoomRegistry = websocket.app.state.social_registry
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
    tap = getattr(websocket.app.state, "ws_debug_tap", None)

    async def agent_send_json(payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False)
        await websocket.send_text(raw)
        if tap is not None:
            await tap.record_outbound_dict(
                channel="agent_ws",
                agent_id=agent_id,
                connection_id=connection_id,
                payload=payload,
                raw=raw,
            )

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
        "social_limits": {
            "max_concurrent_agents_per_room": social.max_concurrent_agents,
            "max_concurrent_observers_per_room": social.max_concurrent_observers,
            "room_idle_hours": settings.social_room_idle_hours,
        },
    }
    await agent_send_json(auth_ok_body)
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

    last_pong_at = time.monotonic()

    async def _heartbeat_server_ping_loop() -> None:
        nonlocal last_pong_at, disconnect_reason
        interval = float(settings.agent_ws_presence_ping_interval_seconds)
        timeout = float(settings.agent_ws_presence_pong_timeout_seconds)
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            if (now - last_pong_at) > timeout:
                disconnect_reason = "pong_timeout"
                try:
                    await websocket.close(code=4008, reason="pong_timeout")
                except Exception:
                    pass
                return
            try:
                await websocket.send_text(json.dumps({"type": "ping"}))
            except Exception:
                return

    heartbeat_task = asyncio.create_task(_heartbeat_server_ping_loop())

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
                    await agent_send_json({"type": "error", "reason": "rate_limit_exceeded"})
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
                if tap is not None:
                    await tap.record_inbound_parse_error(
                        channel="agent_ws",
                        agent_id=agent_id,
                        connection_id=connection_id,
                        byte_len=msg_bytes,
                    )
                await agent_send_json({"type": "error", "reason": "invalid_json"})
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
            if tap is not None and isinstance(data, dict):
                await tap.record_inbound_dict(
                    channel="agent_ws",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    byte_len=msg_bytes,
                    data=data,
                )
            if msg_type == "ping":
                await agent_send_json({"type": "pong"})
                await record_agent_event(
                    session_factory,
                    event="ws_message_out",
                    agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": "pong"},
                )
            elif msg_type == "pong":
                last_pong_at = time.monotonic()
            elif await dispatch_room_inbound_frame(
                websocket,
                social,
                session_factory,
                registry,
                settings,
                agent_id,
                agent.agent_name,
                agent.level,
                msg_type,
                data,
            ):
                pass
            elif msg_type == "publish_news":
                out = await handle_publish_news_ws_message(
                    news_markdown_root=settings.news_markdown_root,
                    public_site_base_url=settings.public_site_base_url,
                    media_public_base_url=settings.media_public_base_url,
                    news_agent_daily_publish_limit=settings.news_agent_daily_publish_limit,
                    session_factory=session_factory,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    data=data,
                    registry=registry,
                )
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "admin_resurrect_social_room":
                social_registry = getattr(websocket.app.state, "social_registry", None)
                out = await handle_admin_resurrect_social_room(
                    session_factory=session_factory,
                    social=social_registry,
                    sovereign_agent_id=agent_id,
                    agent_level=agent.level,
                    connection_id=connection_id,
                    data=data,
                )
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
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
                await agent_send_json(out)
                await record_agent_event(
                    session_factory, event="ws_message_out", agent_id=agent_id,
                    connection_id=connection_id,
                    detail={"message_type": out.get("type"), "reason": out.get("reason")},
                )
            elif msg_type == "command_result":
                request_id = data.get("request_id")
                if not isinstance(request_id, str) or not request_id:
                    await agent_send_json({"type": "error", "reason": "invalid_command_result"})
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
                    await agent_send_json({"type": "error", "reason": "unknown_request_id"})
                    await record_agent_event(
                        session_factory,
                        event="ws_message_out",
                        agent_id=agent_id,
                        connection_id=connection_id,
                        detail={"message_type": "error", "reason": "unknown_request_id"},
                    )
            else:
                await agent_send_json({"type": "error", "reason": "unknown_type"})
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
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        await cleanup_social_room_on_disconnect(
            social=social,
            session_factory=session_factory,
            registry=registry,
            settings=settings,
            agent_id=agent_id,
            agent_name=agent.agent_name,
            connection_id=connection_id,
        )
        if disconnect_reason is not None:
            await record_agent_event(
                session_factory,
                event="ws_disconnected",
                agent_id=agent_id,
                connection_id=connection_id,
                detail={"reason": disconnect_reason},
            )
        await registry.remove_if_current(agent_id, websocket)
