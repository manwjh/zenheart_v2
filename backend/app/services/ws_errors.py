"""
Shared WebSocket error envelopes.

This module contains payload helpers used by `/v2/agent/ws` and related
WebSocket surfaces. It is not a WebSocket endpoint or frame dispatcher.
"""

from __future__ import annotations

from typing import Any


def _entry(
    *,
    message: str,
    hint: str,
    retryable: bool,
    category: str,
    action: str,
) -> dict[str, Any]:
    return {
        "message": message,
        "hint": hint,
        "retryable": retryable,
        "category": category,
        "action": action,
    }


_ERROR_CATALOG: dict[str, dict[str, Any]] = {
    "auth_timeout": _entry(
        message="Authentication timed out before the first auth frame arrived.",
        hint="Open a new WebSocket connection and send the auth frame immediately.",
        retryable=True,
        category="auth",
        action="reconnect_and_authenticate",
    ),
    "invalid_json": _entry(
        message="The frame is not valid JSON.",
        hint="Send one UTF-8 JSON text frame with a valid object payload.",
        retryable=False,
        category="validation",
        action="fix_payload",
    ),
    "expected_auth": _entry(
        message="The first WebSocket frame must be an auth frame.",
        hint='Send {"type":"auth","agent_id":"...","token":"..."} as the first frame.',
        retryable=False,
        category="auth",
        action="authenticate_first",
    ),
    "invalid_payload": _entry(
        message="The request payload is invalid.",
        hint="Check the required fields and their types before retrying.",
        retryable=False,
        category="validation",
        action="fix_payload",
    ),
    "unknown_agent": _entry(
        message="The agent id is not registered.",
        hint="Use a registered agent_id or create/register the agent first.",
        retryable=False,
        category="auth",
        action="use_registered_agent",
    ),
    "revoked": _entry(
        message="The agent credential has been revoked.",
        hint="Ask an operator to rotate or restore the agent credential.",
        retryable=False,
        category="auth",
        action="rotate_credentials",
    ),
    "invalid_token": _entry(
        message="The agent token is invalid.",
        hint="Use the current plaintext token for this agent_id.",
        retryable=False,
        category="auth",
        action="fix_credentials",
    ),
    "rate_limit_exceeded": _entry(
        message="The request exceeded its rate limit.",
        hint="Back off before retrying.",
        retryable=True,
        category="rate_limit",
        action="backoff",
    ),
    "forbidden": _entry(
        message="The agent is not allowed to perform this operation.",
        hint="Check the agent level, permissions, and target resource ownership.",
        retryable=False,
        category="permission",
        action="check_permission",
    ),
    "unknown_type": _entry(
        message="The frame type is not supported on this channel.",
        hint="Use one of the documented frame types for the current WebSocket endpoint.",
        retryable=False,
        category="validation",
        action="fix_frame_type",
    ),
    "not_in_room": _entry(
        message="The agent is not currently a live member of the room.",
        hint="Join the room again before sending messages or reading live room state.",
        retryable=False,
        category="state",
        action="join_room_first",
    ),
    "room_not_found": _entry(
        message="The requested room was not found or is not active.",
        hint="List rooms and use an active room_id.",
        retryable=False,
        category="state",
        action="refresh_state",
    ),
    "room_name_taken": _entry(
        message="An active room already uses this name.",
        hint="Choose a different room name.",
        retryable=False,
        category="conflict",
        action="choose_different_value",
    ),
    "not_room_creator": _entry(
        message="Only the room creator can perform this operation.",
        hint="Use the creator agent or choose a room operation available to members.",
        retryable=False,
        category="permission",
        action="check_permission",
    ),
    "persistence_failed": _entry(
        message="The server could not persist the requested change.",
        hint="Retry later; if it repeats, report the request_id or connection_id to an operator.",
        retryable=True,
        category="server",
        action="retry_later",
    ),
    "internal_error": _entry(
        message="The server hit an internal error while handling the request.",
        hint="Retry later; if it repeats, report the request_id or connection_id to an operator.",
        retryable=True,
        category="server",
        action="retry_later",
    ),
    "unknown_request_id": _entry(
        message="The request_id does not match a pending server request.",
        hint="Reply only to active requests received on this connection.",
        retryable=False,
        category="state",
        action="refresh_state",
    ),
    "invalid_command_result": _entry(
        message="The command result frame is invalid.",
        hint="Send a command_result frame with the required request_id and result fields.",
        retryable=False,
        category="validation",
        action="fix_payload",
    ),
    "join_room_internal_error": _entry(
        message="The server failed while completing join_room.",
        hint="Retry join_room. If it repeats, check server logs for this connection.",
        retryable=True,
        category="server",
        action="retry_join",
    ),
}


def ws_error(
    code: str,
    *,
    message: str | None = None,
    hint: str | None = None,
    retryable: bool | None = None,
    category: str | None = None,
    action: str | None = None,
    detail: Any | None = None,
    field: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "error",
        "reason": code,
        "code": code,
    }
    if detail is not None:
        payload["detail"] = detail
    if field is not None:
        payload["field"] = field
    payload.update(extra)
    return enrich_error_payload(
        payload,
        message=message,
        hint=hint,
        retryable=retryable,
        category=category,
        action=action,
    )


def auth_fail_error(code: str) -> dict[str, Any]:
    payload = enrich_error_payload({"type": "auth_fail", "reason": code})
    payload["retryable"] = bool(_ERROR_CATALOG.get(code, {}).get("retryable", False))
    return payload


def http_error_body(
    code: str,
    *,
    detail: Any | None = None,
    message: str | None = None,
    hint: str | None = None,
    retryable: bool | None = None,
    category: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    error = ws_error(
        code,
        detail=detail,
        message=message,
        hint=hint,
        retryable=retryable,
        category=category,
        action=action,
    )
    error.pop("type", None)
    error.pop("reason", None)
    return {
        "detail": detail if detail is not None else error["message"],
        "error": error,
    }


def enrich_error_payload(
    payload: dict[str, Any],
    *,
    message: str | None = None,
    hint: str | None = None,
    retryable: bool | None = None,
    category: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    frame_type = payload.get("type")
    if frame_type not in {"error", "auth_fail", "subscribe_fail"}:
        return payload

    code = payload.get("code") or payload.get("reason")
    if not isinstance(code, str) or not code:
        return payload

    enriched = dict(payload)
    enriched.setdefault("code", code)
    enriched.setdefault("reason", code)

    derived = _derive_error_fields(code, enriched.get("detail"))
    enriched.setdefault("message", message or derived["message"])
    enriched.setdefault("hint", hint or derived["hint"])
    enriched.setdefault("retryable", retryable if retryable is not None else derived["retryable"])
    enriched.setdefault("category", category or derived["category"])
    enriched.setdefault("action", action or derived["action"])
    return enriched


def _derive_error_fields(code: str, detail: Any | None) -> dict[str, Any]:
    catalog_entry = _ERROR_CATALOG.get(code)
    if catalog_entry is not None:
        fields = dict(catalog_entry)
        if isinstance(detail, str) and detail and code.startswith("invalid_"):
            fields["hint"] = detail
        return fields

    if code.startswith("invalid_") or code.endswith("_payload"):
        return {
            "message": "The request payload is invalid.",
            "hint": detail if isinstance(detail, str) and detail else "Check required fields and types.",
            "retryable": False,
            "category": "validation",
            "action": "fix_payload",
        }

    if code.endswith("_not_found") or code.startswith("unknown_"):
        return {
            "message": "The requested resource was not found.",
            "hint": "Refresh current state and use a known id.",
            "retryable": False,
            "category": "state",
            "action": "refresh_state",
        }

    if code.endswith("_limit_reached"):
        return {
            "message": "The request exceeded a configured limit.",
            "hint": detail if isinstance(detail, str) and detail else "Wait for the limit window to reset.",
            "retryable": True,
            "category": "limit",
            "action": "wait_for_limit_reset",
        }

    return {
        "message": f"Request failed with code: {code}.",
        "hint": detail if isinstance(detail, str) and detail else "Check the request payload and current agent state.",
        "retryable": False,
        "category": "unknown",
        "action": "inspect_error",
    }
