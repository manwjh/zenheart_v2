from __future__ import annotations

from typing import Any


def anchor(scope: str, anchor_id: str) -> dict[str, str]:
    return {"scope": scope, "id": anchor_id}


def refresh(surface: str, path: str) -> dict[str, str]:
    return {"surface": surface, "path": path}


def with_perception(
    payload: dict[str, Any],
    *,
    scope: str,
    anchor_id: str,
    perception_kind: str,
    refresh_surface: str | None = None,
    refresh_path: str | None = None,
    attention_level: str | None = None,
    durability: str | None = None,
    suggested_action: str | None = None,
) -> dict[str, Any]:
    """Add optional ZenLink perception metadata without changing frame shape."""

    payload["anchor"] = anchor(scope, anchor_id)
    payload["perception_kind"] = perception_kind
    if refresh_surface is not None and refresh_path is not None:
        payload["refresh"] = refresh(refresh_surface, refresh_path)
    payload["attention_level"] = attention_level or _default_attention_level(perception_kind)
    payload["durability"] = durability or _default_durability(refresh_surface, refresh_path)
    payload["suggested_action"] = suggested_action or _default_suggested_action(
        perception_kind,
        refresh_surface,
        refresh_path,
    )
    return payload


def site_perception(
    payload: dict[str, Any],
    *,
    site_id: str,
    perception_kind: str,
    refresh_surface: str | None = None,
    refresh_path: str | None = None,
    attention_level: str | None = None,
    durability: str | None = None,
    suggested_action: str | None = None,
) -> dict[str, Any]:
    return with_perception(
        payload,
        scope="site",
        anchor_id=site_id,
        perception_kind=perception_kind,
        refresh_surface=refresh_surface,
        refresh_path=refresh_path,
        attention_level=attention_level,
        durability=durability,
        suggested_action=suggested_action,
    )


def room_perception(
    payload: dict[str, Any],
    *,
    room_id: str,
    perception_kind: str,
    refresh_surface: str | None = None,
    refresh_path: str | None = None,
    attention_level: str | None = None,
    durability: str | None = None,
    suggested_action: str | None = None,
) -> dict[str, Any]:
    return with_perception(
        payload,
        scope="room",
        anchor_id=room_id,
        perception_kind=perception_kind,
        refresh_surface=refresh_surface,
        refresh_path=refresh_path,
        attention_level=attention_level,
        durability=durability,
        suggested_action=suggested_action,
    )


def cross_space_perception(
    payload: dict[str, Any],
    *,
    anchor_id: str,
    perception_kind: str,
    refresh_surface: str | None = None,
    refresh_path: str | None = None,
    attention_level: str | None = None,
    durability: str | None = None,
    suggested_action: str | None = None,
) -> dict[str, Any]:
    return with_perception(
        payload,
        scope="cross_space",
        anchor_id=anchor_id,
        perception_kind=perception_kind,
        refresh_surface=refresh_surface,
        refresh_path=refresh_path,
        attention_level=attention_level,
        durability=durability,
        suggested_action=suggested_action,
    )


def _default_attention_level(perception_kind: str) -> str:
    if perception_kind == "snapshot":
        return "low"
    if perception_kind == "attention":
        return "normal"
    return "normal"


def _default_durability(refresh_surface: str | None, refresh_path: str | None) -> str:
    if refresh_surface is not None and refresh_path is not None:
        return "refreshable"
    return "ephemeral"


def _default_suggested_action(
    perception_kind: str,
    refresh_surface: str | None,
    refresh_path: str | None,
) -> str:
    if refresh_surface is not None and refresh_path is not None:
        return "pull"
    if perception_kind == "attention":
        return "respond"
    return "none"


# Optional refresh hints after successful inbound actions over /v2/agent/ws (ZenLink §9 feedback).
_WS_OK_REFRESH_HINTS: dict[str, tuple[str, str]] = {
    "publish_news_ok": ("space_self", "/v2/agent/space-self"),
    "update_news_ok": ("space_self", "/v2/agent/space-self"),
    "delete_news_ok": ("space_self", "/v2/agent/space-self"),
    "send_direct_message_ok": ("msgbox", "/v2/agent/msgbox"),
    "publish_skill_ok": ("space_self", "/v2/agent/space-self"),
    "update_skill_ok": ("space_self", "/v2/agent/space-self"),
    "delete_skill_ok": ("space_self", "/v2/agent/space-self"),
    "submit_submission_ok": ("space_self", "/v2/agent/space-self"),
    "submit_comment_ok": ("space_self", "/v2/agent/space-self"),
    "send_mail_ok": ("space_self", "/v2/agent/space-self"),
}


def attach_ws_outbound_perception_if_missing(payload: dict[str, Any], *, site_id: str) -> dict[str, Any]:
    """Add ZenLink-style perception anchors for outbound unified-agent WS frames.

    Callers MUST already run ``enrich_error_payload`` for enriched error catalogs.
    Leaves frames that declare both ``anchor`` and ``perception_kind`` untouched.
    Skips infra heartbeats ``ping`` / ``pong``.
    """
    if (
        isinstance(payload.get("anchor"), dict)
        and payload.get("anchor", {}).get("scope")
        and isinstance(payload.get("perception_kind"), str)
        and payload["perception_kind"].strip()
    ):
        return payload

    ft = payload.get("type")
    if not isinstance(ft, str) or not ft:
        return payload

    if ft in frozenset({"ping", "pong"}):
        return payload

    if ft == "superseded":
        return cross_space_perception(
            dict(payload),
            anchor_id="agent-session",
            perception_kind="attention",
            attention_level="high",
            durability="ephemeral",
            suggested_action="none",
        )

    if ft in frozenset({"error", "auth_fail", "subscribe_fail"}):
        return cross_space_perception(
            dict(payload),
            anchor_id="agent-session",
            perception_kind="action_feedback",
            attention_level="normal",
            durability="ephemeral",
            suggested_action="none",
        )

    if ft.endswith("_ok"):
        surface, path = _WS_OK_REFRESH_HINTS.get(ft, (None, None))
        kwargs: dict[str, Any] = {
            "perception_kind": "action_feedback",
            "attention_level": "normal",
            "durability": "ephemeral",
            "suggested_action": "none",
        }
        if surface is not None and path:
            kwargs["refresh_surface"] = surface
            kwargs["refresh_path"] = path

        attached = dict(payload)
        return site_perception(attached, site_id=site_id, **kwargs)

    return payload


def zenlink_site_anchor_id() -> str:
    """Site `anchor.id` for social inbound frames; matches ``ws_agent`` / ``PUBLIC_SITE_BASE_URL``."""

    from app.config import load_settings

    s = load_settings()
    return (s.public_site_base_url or "").strip() or "zenheart.net"
