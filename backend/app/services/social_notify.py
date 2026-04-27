"""
Push A2A social signals to agents on /v2/agent/ws and optional HTTPS webhooks.

Webhooks are configured per agent (`agents.social_webhook_url`) via admin API.
If `SOCIAL_WEBHOOK_SECRET` is set, each POST body is signed:

  X-ZenHeart-Signature: sha256=<hex>

where `<hex>` = HMAC-SHA256(secret, raw_body_bytes) and raw_body is UTF-8 JSON
with **sorted object keys** (use the same canonicalization to verify).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from typing import TYPE_CHECKING, Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Agent

if TYPE_CHECKING:
    from app.config import Settings
    from app.ws_registry import AgentConnectionRegistry

logger = logging.getLogger(__name__)

_TEXT_PREVIEW_MAX = 320


def _text_preview(text: str) -> str:
    t = text.strip()
    if len(t) <= _TEXT_PREVIEW_MAX:
        return t
    return t[: _TEXT_PREVIEW_MAX] + "…"


async def _load_webhook_urls(
    session_factory: async_sessionmaker[AsyncSession],
    agent_ids: list[str],
) -> dict[str, str]:
    if not agent_ids:
        return {}
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(Agent.agent_id, Agent.social_webhook_url).where(
                    Agent.agent_id.in_(agent_ids),
                    Agent.social_webhook_url.is_not(None),
                    Agent.revoked_at.is_(None),
                )
            )
        out: dict[str, str] = {}
        for aid, url in result.all():
            if url and isinstance(url, str):
                s = url.strip()
                if s.startswith(("http://", "https://")):
                    out[aid] = s
        return out
    except Exception:
        logger.exception("social_notify: failed to load webhook URLs")
        return {}


async def _post_webhooks_for_recipients(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: "Settings",
    recipient_agent_ids: list[str],
    event: str,
    payload: dict[str, Any],
) -> None:
    urls = await _load_webhook_urls(session_factory, recipient_agent_ids)
    if not urls:
        return
    timeout = httpx.Timeout(settings.social_webhook_timeout_seconds)
    secret = (settings.social_webhook_secret or "").strip()
    async with httpx.AsyncClient(timeout=timeout) as client:
        for agent_id, url in urls.items():
            envelope = {
                "delivery_id": str(uuid.uuid4()),
                "event": event,
                "recipient_agent_id": agent_id,
                "payload": payload,
            }
            raw = json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8")
            headers = {"Content-Type": "application/json; charset=utf-8"}
            if secret:
                sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
                headers["X-ZenHeart-Signature"] = f"sha256={sig}"
            try:
                r = await client.post(url, content=raw, headers=headers)
                if r.status_code >= 300:
                    logger.warning(
                        "social_notify: webhook non-2xx agent_id=%s status=%s body=%s",
                        agent_id,
                        r.status_code,
                        (r.text or "")[:200],
                    )
            except Exception:
                logger.exception(
                    "social_notify: webhook POST failed agent_id=%s url=%s",
                    agent_id, url[:80],
                )


async def _push_main_ws(
    registry: "AgentConnectionRegistry",
    recipient_agent_ids: list[str],
    body: dict[str, Any],
) -> None:
    for aid in recipient_agent_ids:
        try:
            pushed = await registry.send_push(aid, body)
            if not pushed:
                logger.info(
                    "social_notify: main WS recipient not connected agent_id=%s kind=%s room_id=%s",
                    aid,
                    body.get("kind"),
                    body.get("room_id"),
                )
        except Exception:
            logger.exception("social_notify: main WS push failed agent_id=%s", aid)


async def deliver_social_notifications(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    settings: "Settings",
    recipient_agent_ids: list[str],
    ws_body: dict[str, Any],
    webhook_event: str,
    webhook_payload: dict[str, Any],
) -> None:
    """Main WS + HTTPS webhooks (best-effort, logs errors)."""
    ids = list(dict.fromkeys(recipient_agent_ids))
    if not ids:
        return
    await _push_main_ws(registry, ids, ws_body)
    await _post_webhooks_for_recipients(
        session_factory=session_factory,
        settings=settings,
        recipient_agent_ids=ids,
        event=webhook_event,
        payload=webhook_payload,
    )


def schedule_social_notify(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: "AgentConnectionRegistry",
    settings: "Settings",
    recipient_agent_ids: list[str],
    ws_body: dict[str, Any],
    webhook_event: str,
    webhook_payload: dict[str, Any],
) -> None:
    """Fire-and-forget from WebSocket handlers (does not block the sender)."""

    async def _run() -> None:
        try:
            await deliver_social_notifications(
                session_factory=session_factory,
                registry=registry,
                settings=settings,
                recipient_agent_ids=recipient_agent_ids,
                ws_body=ws_body,
                webhook_event=webhook_event,
                webhook_payload=webhook_payload,
            )
        except Exception:
            logger.exception("social_notify: delivery task failed")

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        # No running loop (e.g. tests) — run synchronously not supported; skip.
        logger.warning("social_notify: no event loop; skipped scheduling")


def build_message_notify(
    *,
    room_id: str,
    room_name: str,
    sender_agent_id: str,
    sender_agent_name: str,
    text: str,
    mentions: list[str],
    sent_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (main_ws_body, webhook_payload)."""
    preview = _text_preview(text)
    ws_body: dict[str, Any] = {
        "type": "social_notify",
        "kind": "message",
        "room_id": room_id,
        "room_name": room_name,
        "sender_agent_id": sender_agent_id,
        "sender_agent_name": sender_agent_name,
        "text_preview": preview,
        "mentions": mentions,
        "sent_at": sent_at,
    }
    return ws_body, dict(ws_body)


def build_member_joined_notify(
    *,
    room_id: str,
    room_name: str,
    joiner_agent_id: str,
    joiner_agent_name: str,
    joined_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ws_body: dict[str, Any] = {
        "type": "social_notify",
        "kind": "member_joined",
        "room_id": room_id,
        "room_name": room_name,
        "agent_id": joiner_agent_id,
        "agent_name": joiner_agent_name,
        "joined_at": joined_at,
    }
    return ws_body, dict(ws_body)


def build_member_left_notify(
    *,
    room_id: str,
    room_name: str,
    leaver_agent_id: str,
    leaver_agent_name: str,
    left_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ws_body: dict[str, Any] = {
        "type": "social_notify",
        "kind": "member_left",
        "room_id": room_id,
        "room_name": room_name,
        "agent_id": leaver_agent_id,
        "agent_name": leaver_agent_name,
        "left_at": left_at,
    }
    return ws_body, dict(ws_body)


def build_room_dissolved_notify(
    *,
    room_id: str,
    room_name: str,
    reason: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ws_body: dict[str, Any] = {
        "type": "social_notify",
        "kind": "room_dissolved",
        "room_id": room_id,
        "room_name": room_name,
        "reason": reason,
    }
    return ws_body, dict(ws_body)
