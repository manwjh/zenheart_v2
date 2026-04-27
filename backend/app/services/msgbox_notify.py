"""
Shared helpers for best-effort msgbox_notify pushes on /v2/agent/ws.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.ws_registry import AgentConnectionRegistry

logger = logging.getLogger(__name__)


def build_msgbox_notify_payload(
    *,
    kind: str,
    message_id: str,
    from_agent_id: Optional[str] = None,
    from_name: Optional[str] = None,
    preview: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "msgbox_notify",
        "kind": kind,
        "message_id": message_id,
    }
    if from_agent_id is not None:
        body["from_agent_id"] = from_agent_id
    if from_name is not None:
        body["from_name"] = from_name
    if preview is not None:
        body["preview"] = preview
    if extra:
        body.update(extra)
    return body


async def push_msgbox_notify_to_agent(
    registry: "AgentConnectionRegistry",
    agent_id: str,
    *,
    kind: str,
    message_id: str,
    from_agent_id: Optional[str] = None,
    from_name: Optional[str] = None,
    preview: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    try:
        await registry.send_push(
            agent_id,
            build_msgbox_notify_payload(
                kind=kind,
                message_id=message_id,
                from_agent_id=from_agent_id,
                from_name=from_name,
                preview=preview,
                extra=extra,
            ),
        )
    except Exception:
        logger.exception(
            "msgbox_notify: failed kind=%s message_id=%s agent_id=%s",
            kind,
            message_id,
            agent_id,
        )
