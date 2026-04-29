"""
Admin-only observer for real third-party agent WebSocket traffic: HTML at GET /v2/admin/debug/ws,
JSON feed at GET /v2/admin/debug/ws/feed.

Does not open or simulate WS from the browser—polls server-side tap/registry snapshots.
The page is unauthenticated (returns static HTML). The feed requires header X-Admin-Key.
Set DEBUG_WS_MONITOR_ENABLED=false to disable the JSON /feed only (HTML page still loads).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette import status
from fastapi.responses import HTMLResponse

from app.config import Settings
from app.deps import DbSession, SettingsDep, admin_key_guard, get_settings
from app.services.display_name_resolve import load_agent_name_map

router = APIRouter(prefix="/v2/admin/debug", tags=["admin-debug"])

_HTML_PATH = Path(__file__).resolve().parent.parent / "templates" / "debug_ws_monitor.html"


def _require_monitor_feed(settings: Settings) -> None:
    """JSON feed only; keep disabled in production via env without hiding the HTML page."""
    if not settings.debug_ws_monitor_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="DEBUG_WS_MONITOR_ENABLED is false; set to true (and redeploy) to enable /feed.",
        )


def require_monitor_feed_enabled(settings: SettingsDep) -> None:
    _require_monitor_feed(settings)


@router.get("/ws", response_class=HTMLResponse)
async def debug_ws_page(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    # Always return HTML (200): production often set DEBUG_WS_MONITOR_ENABLED=false which
    # previously made this URL 404 and looked like a bad link; /feed stays gated separately.
    try:
        body = _HTML_PATH.read_text(encoding="utf-8")
    except OSError:
        body = (
            "<!doctype html><html><head><meta charset=utf-8><title>WS debug</title></head><body>"
            "<p>Template missing.</p><script>const ZH_FEED_OK = ___ZH_FEED___;</script></body></html>"
        )
    flag = "true" if settings.debug_ws_monitor_enabled else "false"
    body = body.replace("___ZH_FEED___", flag)
    return HTMLResponse(body)


@router.get(
    "/ws/feed",
    dependencies=[
        Depends(require_monitor_feed_enabled),
        Depends(admin_key_guard),
    ],
)
async def debug_ws_feed(
    request: Request,
    session: DbSession,
    since: int = Query(0, ge=0),
) -> dict[str, Any]:
    tap = getattr(request.app.state, "ws_debug_tap", None)
    registry = request.app.state.registry
    connections = await registry.list_connections_debug()
    events: list[dict[str, Any]] = []
    max_seq = 0
    if tap is not None:
        events, max_seq = await tap.events_since(since, limit=200)

    id_set: set[str] = {c["agent_id"] for c in connections if c.get("agent_id")}
    for e in events:
        aid = e.get("agent_id")
        if isinstance(aid, str) and aid:
            id_set.add(aid)
    agent_names = await load_agent_name_map(session, id_set)
    for c in connections:
        aid = c.get("agent_id")
        if isinstance(aid, str) and aid in agent_names:
            c["agent_name"] = agent_names[aid]
        else:
            c["agent_name"] = None

    return {
        "connections": connections,
        "events": events,
        "max_seq": max_seq,
        "agent_names": agent_names,
    }
