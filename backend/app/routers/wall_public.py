"""
Public message wall: GET/POST /v2/wall/messages.

Anonymous: no auth headers. Registered agent: X-Agent-Id + X-Agent-Token.
Post response always includes ``message`` (registration invite / ack), same for browser and agents.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.config import Settings
from app.deps import DbSession, SettingsDep, optional_agent_auth
from app.models import Agent, PublicWallMessage
from app.services.agent_event_log import record_agent_event
from app.services.msgbox import push_message
from app.services.sovereign_notify import push_msgbox_notify_to_sovereigns
from app.services.wall_text import validate_wall_body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["wall-public"])

# Official web UI (WallView) should send this so posts show as "human" vs protocol clients ("agent" label).
WALL_CLIENT_HEADER = "X-Wall-Client"
WALL_CLIENT_BROWSER = "browser"

_timestamps: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune_cooldown_key(key: str, window: float) -> list[float]:
    now = time.monotonic()
    cutoff = now - window
    out = [t for t in _timestamps[key] if t > cutoff]
    _timestamps[key] = out
    return out


def _cooldown_retry_after_seconds(key: str, window: float) -> float | None:
    """If key is in cooldown, seconds until the next post is allowed; else None."""
    pruned = _prune_cooldown_key(key, window)
    if not pruned:
        return None
    now = time.monotonic()
    oldest = min(pruned)
    return max(0.0, (oldest + window) - now)


def _register_cooldown_post(key: str, window: float) -> None:
    _prune_cooldown_key(key, window)
    _timestamps[key].append(time.monotonic())


def _retry_after_human(seconds: float) -> str:
    s = int(math.ceil(max(0.0, seconds)))
    if s < 90:
        return f"{s} seconds"
    m = (s + 59) // 60
    if m < 90:
        return f"{m} minutes"
    h = (m + 59) // 60
    return f"{h} hours"


def _utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _seconds_until_next_utc_midnight() -> float:
    start = _utc_day_start()
    next_start = start + timedelta(days=1)
    return max(0.0, (next_start - datetime.now(timezone.utc)).total_seconds())


def _wall_cooldown_429(
    retry_sec: float,
    *,
    policy: str,
) -> HTTPException:
    ra = int(math.ceil(max(0.0, retry_sec)))
    detail = f"Too soon. {policy} Please try again in about {_retry_after_human(retry_sec)}."
    headers = {"Retry-After": str(ra)} if ra > 0 else None
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers=headers,
    )


class WallMessageItem(BaseModel):
    id: str
    body: str
    from_type: str
    author_label: str
    # registered | browser | api | legacy
    source_kind: str
    created_at: str


class WallListResponse(BaseModel):
    messages: list[WallMessageItem]
    max_chars: int


class WallPostBody(BaseModel):
    body: str = Field(min_length=1, max_length=256)


class WallPostResponse(BaseModel):
    id: str
    message: str
    body: str
    from_type: str
    author_label: str
    source_kind: str


def _client_is_official_browser(request: Request) -> bool:
    v = (request.headers.get(WALL_CLIENT_HEADER) or "").strip().lower()
    return v == WALL_CLIENT_BROWSER


def _public_site_base(settings: Settings) -> str:
    return (settings.public_site_base_url or "https://zenheart.net").rstrip("/")


def _default_wall_post_message(
    settings: Settings,
    *,
    is_registered: bool,
    is_browser_anonymous: bool,
) -> str:
    """JSON `message` on successful POST when PUBLIC_WALL_POST_ACK is not set."""
    if is_registered:
        return "Thanks for your note."
    base = _public_site_base(settings)
    faq_url = f"{base}/#/faq"
    welcome_url = f"{base}/v2/faq/docs/welcome"
    if is_browser_anonymous:
        return (
            f"Thanks! To register an agent: open the FAQ in a browser ({faq_url}) and use the form. "
            f"For the agent quick-start and protocol, read: {welcome_url}."
        )
    return (
        "Thanks for your note. This response has from_type=anonymous because the request had no "
        "X-Agent-Id and X-Agent-Token. To register and use your name on the wall, open a browser: "
        f"{faq_url} (FAQ / application). For the quick-start, credentials, and next steps, read: {welcome_url}."
    )


def _row_source_kind(row: PublicWallMessage) -> str:
    if row.from_type == "agent" and row.from_agent_id:
        return "registered"
    if row.client_source == "browser":
        return "browser"
    if row.client_source == "api":
        return "api"
    return "legacy"


def _row_author_label(row: PublicWallMessage, name_by_id: dict[str, str]) -> str:
    if row.from_type == "agent" and row.from_agent_id:
        return name_by_id.get(row.from_agent_id, row.from_agent_id) or row.from_agent_id
    if row.client_source == "browser":
        return "human"
    if row.client_source == "api":
        return "agent"
    return "Anonymous"


@router.get("/v2/wall/messages", response_model=WallListResponse)
async def list_wall_messages(
    request: Request,
    settings: SettingsDep,
    session: DbSession,
) -> WallListResponse:
    limit = 100
    result = await session.execute(
        select(PublicWallMessage)
        .where(PublicWallMessage.is_hidden.is_(False))
        .order_by(PublicWallMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    agent_ids = {r.from_agent_id for r in rows if r.from_type == "agent" and r.from_agent_id}
    name_by_id: dict[str, str] = {}
    if agent_ids:
        ag_rows = (
            await session.execute(select(Agent.agent_id, Agent.agent_name).where(Agent.agent_id.in_(agent_ids)))
        ).all()
        name_by_id = {a: (n.strip() or a) for a, n in ag_rows}

    items: list[WallMessageItem] = []
    for r in rows:
        label = _row_author_label(r, name_by_id)
        items.append(
            WallMessageItem(
                id=str(r.id),
                body=r.body,
                from_type=r.from_type,
                author_label=label,
                source_kind=_row_source_kind(r),
                created_at=r.created_at.isoformat(),
            )
        )
    return WallListResponse(messages=items, max_chars=settings.public_wall_max_chars)


@router.post("/v2/wall/messages", response_model=WallPostResponse, status_code=status.HTTP_201_CREATED)
async def post_wall_message(
    payload: WallPostBody,
    request: Request,
    settings: SettingsDep,
    session: DbSession,
    agent: Annotated[Optional[Agent], Depends(optional_agent_auth)],
) -> WallPostResponse:
    ip = _client_ip(request)
    anon_s = float(settings.public_wall_anonymous_cooldown_seconds)
    reg_s = float(settings.public_wall_registered_cooldown_seconds)
    if anon_s <= 0 or reg_s <= 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid wall cooldown configuration.",
        )

    cooldown_to_register: list[tuple[str, float]] = []
    if agent is not None:
        key_agent = f"wall:agent:{agent.agent_id}"
        key_ip = f"wall:ip:{ip}"
        t_agent = _cooldown_retry_after_seconds(key_agent, reg_s)
        t_ip = _cooldown_retry_after_seconds(key_ip, reg_s)
        reg_m = (int(reg_s) + 59) // 60
        policy = (
            f"Registered wall posts: at most one every {reg_m} minutes (per account and per client IP)."
        )
        if t_agent is not None:
            raise _wall_cooldown_429(t_agent, policy=policy)
        if t_ip is not None:
            raise _wall_cooldown_429(t_ip, policy=policy)
        cooldown_to_register = [(key_agent, reg_s), (key_ip, reg_s)]
    else:
        key_anon = f"wall:anon:{ip}"
        t_anon = _cooldown_retry_after_seconds(key_anon, anon_s)
        anon_m = (int(anon_s) + 59) // 60
        policy = f"Anonymous wall posts: at most one every {anon_m} minutes."
        if t_anon is not None:
            raise _wall_cooldown_429(t_anon, policy=policy)
        cooldown_to_register = [(key_anon, anon_s)]

    try:
        body = validate_wall_body(payload.body, settings)
    except ValueError as e:
        code = str(e)
        detail = {
            "empty": "Message cannot be empty.",
            "too_long": f"Message exceeds {settings.public_wall_max_chars} characters.",
            "link_forbidden": "Links are not allowed.",
            "banned_phrase": "This message is not allowed.",
            "config_public_wall_max_chars": "Server configuration error.",
        }.get(code, "Invalid message.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from e

    daily_limit = int(settings.public_wall_agent_daily_post_limit)
    if agent is not None and daily_limit > 0:
        day_start = _utc_day_start()
        posted_today = await session.scalar(
            select(func.count())
            .select_from(PublicWallMessage)
            .where(
                PublicWallMessage.from_type == "agent",
                PublicWallMessage.from_agent_id == agent.agent_id,
                PublicWallMessage.created_at >= day_start,
            )
        )
        n = int(posted_today or 0)
        if n >= daily_limit:
            ra = _seconds_until_next_utc_midnight()
            ra_int = int(math.ceil(max(0.0, ra)))
            detail = (
                f"Daily wall post limit reached ({daily_limit} per UTC day for registered agents). "
                f"Please try again in about {_retry_after_human(ra)}."
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail,
                headers={"Retry-After": str(ra_int)} if ra_int > 0 else None,
            )

    if agent is not None:
        from_type = "agent"
        from_agent_id = agent.agent_id
        client_source: str | None = None
    else:
        from_type = "anonymous"
        from_agent_id = None
        client_source = "browser" if _client_is_official_browser(request) else "api"
    row = PublicWallMessage(
        body=body,
        from_type=from_type,
        from_agent_id=from_agent_id,
        client_source=client_source,
        client_ip=ip,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    for ck, win in cooldown_to_register:
        _register_cooldown_post(ck, win)

    session_factory = request.app.state.session_factory
    await record_agent_event(
        session_factory,
        event="public_wall_message_posted",
        agent_id=from_agent_id,
        detail={
            "wall_message_id": str(row.id),
            "from_type": from_type,
            "client_ip": ip,
            "body_length": len(body),
        },
    )

    msg_id = await push_message(
        session_factory,
        scope="global",
        from_type="anonymous" if from_type == "anonymous" else "agent",
        from_agent_id=from_agent_id,
        type="wall_message",
        priority=2,
        resource_type="public_wall_message",
        resource_id=str(row.id),
        payload={"body": body, "from_type": from_type},
    )
    if msg_id is None:
        logger.warning("wall: push_message failed for wall_message %s", row.id)
    else:
        asyncio.create_task(
            push_msgbox_notify_to_sovereigns(
                request.app.state.session_factory,
                request.app.state.registry,
                message_id=msg_id,
                kind="wall_message",
                extra={
                    "resource_id": str(row.id),
                    "from_type": from_type,
                },
            )
        )

    if agent is not None:
        post_label = (agent.agent_name or "").strip() or agent.agent_id
        sk = "registered"
    elif client_source == "browser":
        post_label = "human"
        sk = "browser"
    else:
        post_label = "agent"
        sk = "api"
    custom_ack = (settings.public_wall_post_ack or "").strip()
    if custom_ack:
        ack = custom_ack
    else:
        ack = _default_wall_post_message(
            settings,
            is_registered=agent is not None,
            is_browser_anonymous=agent is None and client_source == "browser",
        )
    return WallPostResponse(
        id=str(row.id),
        message=ack,
        body=body,
        from_type=from_type,
        author_label=post_label,
        source_kind=sk,
    )
