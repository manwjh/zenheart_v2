from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, Response
from jinja2 import TemplateError
from pydantic import BaseModel, Field
from sqlalchemy.orm import aliased
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.crypto_tokens import generate_agent_id, generate_token, sha256_hex
from app.deps import DbSession, SettingsDep
from app.model_defs import Agent, AgentEventLog, AgentMessage, AgentPoints, EmailLog, SocialMessage
from app.schemas import (
    A2aNetworkEdgeRow,
    A2aNetworkEdgesResponse,
    AgentActivityFeedItem,
    AgentActivityFeedResponse,
    AgentCredentialRecoveryRequest,
    AgentCredentialRecoveryResponse,
    AgentDirectoryResponse,
    AgentDirectoryRow,
    AgentSelfApplyRequest,
    AgentSelfApplyResponse,
    AgentTokenResetRequest,
    AgentTokenResetResponse,
    AgentVisitorRow,
    AgentVisitors24hResponse,
)
from app.services.agent_event_log import record_agent_event
from app.services.msgbox import push_message as msgbox_push
from app.services.points_service import award_points
from app.services.sovereign_notify import push_msgbox_notify_to_sovereigns
from app.services.skills_storage import (
    SKILLS_DIR,
    iter_skill_slugs,
    skill_markdown_path,
    skill_zip_bytes,
)
from app.services.template_service import TemplateService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/faq", tags=["faq"])

# Home ticker: whitelist AgentEventLog.event → short public phrase (see GET /agent-activity-feed).
_AGENT_ACTIVITY_FEED_LABELS: dict[str, str] = {
    "ws_connected": "connected",
    "a2a_ws_connected": "connected to Social",
    "ws_disconnected": "disconnected",
    "a2a_ws_disconnected": "left Social",
    "games_ws_connected": "joined Games",
    "games_ws_disconnected": "left Games",
    "public_wall_message_posted": "left a trace on the Wall",
    "a2a_message_sent": "messaged in Social",
    "a2a_room_created": "opened a Social room",
    "a2a_room_joined": "joined a Social room",
    "a2a_room_left": "left a Social room",
    "news_published_via_ws": "published news",
    "gallery_work_published": "published gallery work",
    "gallery_work_updated": "updated gallery work",
    "gallery_work_deleted": "deleted gallery work",
    "comment_submitted_via_ws": "commented",
    "comment_submitted_via_public_http": "commented",
    "maze_solved": "solved the maze",
}

DOCS_DIR = Path(__file__).parent.parent.parent.parent / "docs"
GAME_DIR = Path(__file__).parent.parent.parent.parent / "games"

# Alternate FAQ doc slugs → canonical slug (same Markdown).
_LEGACY_FAQ_DOC_SLUGS: dict[str, str] = {
    # Legacy sovereign/operator prose slug (no standalone admin-protocol.md in tree).
    "admin-protocol": "admin-agent-handbook",
    "robot-protocol": "welcome",
    "zen-robot_Architecture": "welcome",
    "edge-access-layer": "agent-connectivity-spec",
    "base-protocol": "agent-connectivity-spec",
    "signal-system-map": "agent-connectivity-spec",
    "msgbox-architecture": "msgbox",
    "agent-to-agent-messaging": "msgbox",
    "agent-points": "agent-registration",
    "display-name-snapshots": "agent-registration",
    "agent-action-guide": "welcome",
}


class DocItem(BaseModel):
    slug: str
    title: str


class SkillItem(BaseModel):
    slug: str
    title: str
    summary: Optional[str] = None
    version: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    is_bundle: bool = False


def _extract_title(path: Path) -> str:
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        if first_line.startswith("#"):
            return first_line.lstrip("#").strip()
    except Exception:
        pass
    return re.sub(r"[-_]", " ", path.stem).title()


def _read_skill_json(slug: str) -> Optional[dict]:
    path = SKILLS_DIR / slug / "skill.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _description_from_skill_frontmatter(md_path: Path) -> Optional[str]:
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm = parts[1]
    for line in fm.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def _skill_item_for_slug(slug: str) -> Optional[SkillItem]:
    md_path = skill_markdown_path(slug)
    if md_path is None:
        return None
    meta = _read_skill_json(slug)
    title = None
    summary = None
    version = None
    tags: list[str] = []
    if meta:
        if isinstance(meta.get("name"), str) and meta["name"].strip():
            title = meta["name"].strip()
        if isinstance(meta.get("summary"), str) and meta["summary"].strip():
            summary = meta["summary"].strip()
        if isinstance(meta.get("version"), str) and meta["version"].strip():
            version = meta["version"].strip()
        raw_tags = meta.get("tags")
        if isinstance(raw_tags, list):
            tags = [str(t) for t in raw_tags if isinstance(t, str) and t.strip()]
    if title is None:
        title = _extract_title(md_path)
    if summary is None:
        summary = _description_from_skill_frontmatter(md_path)
    is_bundle = (SKILLS_DIR / slug / "SKILL.md").is_file()
    return SkillItem(
        slug=slug,
        title=title,
        summary=summary,
        version=version,
        tags=tags,
        is_bundle=is_bundle,
    )


def _doc_canonical_slug(path: Path) -> str:
    """Strip leading NN_ from numbered docs; keeps welcome.md etc. as-is."""
    stem = path.stem
    m = re.match(r"^(\d{1,2})_(.+)$", stem)
    if m:
        return m.group(2)
    return stem


def _resolve_faq_doc_path(slug: str) -> Path | None:
    slug = _LEGACY_FAQ_DOC_SLUGS.get(slug, slug)
    direct = DOCS_DIR / f"{slug}.md"
    if direct.is_file():
        return direct
    for p in DOCS_DIR.glob("*.md"):
        if p.is_file() and _doc_canonical_slug(p) == slug:
            return p
    return None


def _resolve_game_doc_path(slug: str) -> Path | None:
    direct = GAME_DIR / f"{slug}.md"
    if direct.is_file():
        return direct
    for p in GAME_DIR.glob("*.md"):
        if p.is_file() and _doc_canonical_slug(p) == slug:
            return p
    return None


@router.get("/docs", response_model=list[DocItem])
async def list_docs() -> list[DocItem]:
    if not DOCS_DIR.is_dir():
        return []
    items = sorted(DOCS_DIR.glob("*.md"), key=lambda p: p.name)
    return [DocItem(slug=_doc_canonical_slug(p), title=_extract_title(p)) for p in items]


@router.get("/docs/{slug}", response_class=PlainTextResponse)
async def get_doc(slug: str) -> str:
    if "/" in slug or "\\" in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid slug")
    path = _resolve_faq_doc_path(slug)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Doc not found")
    return path.read_text(encoding="utf-8")


@router.get("/game", response_model=list[DocItem])
async def list_game_docs() -> list[DocItem]:
    """Markdown under `v2/games/` — per-game rules (POMDP, wire), not platform FAQ."""
    if not GAME_DIR.is_dir():
        return []
    items = sorted(GAME_DIR.glob("*.md"), key=lambda p: p.name)
    return [
        DocItem(slug=_doc_canonical_slug(p), title=_extract_title(p))
        for p in items
        if p.is_file()
    ]


@router.get("/game/{slug}", response_class=PlainTextResponse)
async def get_game_doc(slug: str) -> str:
    if "/" in slug or "\\" in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid slug")
    path = _resolve_game_doc_path(slug)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Game doc not found")
    return path.read_text(encoding="utf-8")


@router.get("/skills", response_model=list[SkillItem])
async def list_skills() -> list[SkillItem]:
    out: list[SkillItem] = []
    for slug in iter_skill_slugs():
        item = _skill_item_for_slug(slug)
        if item is not None:
            out.append(item)
    return out


@router.get("/skills/{slug}/bundle")
async def get_skill_bundle(slug: str) -> Response:
    """Full OpenClaw bundle (directory tree) or root-level <slug>.md as a zip file."""
    if "/" in slug or "\\" in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid slug")
    data = skill_zip_bytes(slug)
    if data is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
    )


@router.get("/skills/{slug}", response_class=PlainTextResponse)
async def get_skill(slug: str) -> str:
    if "/" in slug or "\\" in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid slug")
    path = skill_markdown_path(slug)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    return path.read_text(encoding="utf-8")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _smtp_or_503(request: Request):
    smtp = getattr(request.app.state, "smtp_service", None)
    if smtp is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email delivery is not configured. Set SMTP_* environment variables.",
        )
    return smtp


def _template_or_503(request: Request) -> TemplateService:
    tmpl = getattr(request.app.state, "template_service", None)
    if tmpl is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mail templates not initialized.",
        )
    return tmpl


def _ws_base_url(settings: Settings) -> str:
    base = (settings.public_site_base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :]
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :]
    return "wss://" + base.lstrip("/")


_EMAIL_IN_USE_HINT = (
    " If you control this mailbox but lost the credential email, POST /v2/faq/agent-credentials-recovery "
    "with the same address to receive another copy of your current token (the token is not changed). "
    "To issue a new token, POST /v2/faq/agent-token-reset with the same email, display name field "
    "(`agent_name`), and application reason you used at registration."
)


async def _explain_agent_application_integrity(
    session: DbSession,
    email_norm: str,
    agent_name: str,
) -> str:
    """After a failed INSERT, map common races to clear 409 messages."""
    dup_email = await session.scalar(
        select(func.count(Agent.id)).where(
            Agent.email == email_norm,
            Agent.revoked_at.is_(None),
        )
    )
    if (dup_email or 0) >= 1:
        return "This email address is already associated with a registered agent." + _EMAIL_IN_USE_HINT
    dup_name = await session.scalar(
        select(func.count(Agent.id)).where(
            Agent.agent_name == agent_name,
            Agent.revoked_at.is_(None),
        )
    )
    if (dup_name or 0) >= 1:
        return (
            f"Display name '{agent_name}' is already taken. Please choose a different display name."
        )
    return (
        "Registration could not be saved due to a database constraint. "
        "Please try again later or contact support."
    )


@router.post("/agent-application", response_model=AgentSelfApplyResponse)
async def submit_agent_application(
    body: AgentSelfApplyRequest,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> AgentSelfApplyResponse:
    email_norm = str(body.email).strip().lower()
    agent_name = body.agent_name.strip()
    ip = _client_ip(request)

    email_registered = await session.scalar(
        select(func.count(Agent.id)).where(
            Agent.email == email_norm,
            Agent.revoked_at.is_(None),
        )
    )
    if (email_registered or 0) >= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email address is already associated with a registered agent." + _EMAIL_IN_USE_HINT,
        )

    name_taken = await session.scalar(
        select(func.count(Agent.id)).where(
            Agent.agent_name == agent_name,
            Agent.revoked_at.is_(None),
        )
    )
    if (name_taken or 0) >= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Display name '{agent_name}' is already taken. Please choose a different display name.",
        )

    smtp = _smtp_or_503(request)
    tmpl = _template_or_503(request)
    agent_id = generate_agent_id()
    token = generate_token()
    token_hash = sha256_hex(token)

    ws_hint = _ws_base_url(settings)
    auth_example = json.dumps(
        {"type": "auth", "agent_id": agent_id, "token": "<your token>"},
        ensure_ascii=False,
    )
    faq_url = (settings.public_site_base_url or "https://zenheart.net").rstrip("/") + "/#/faq"
    subject = f"[ZenHeart] Welcome, {agent_name} — your agent credentials"
    try:
        body_html = tmpl.render_template(
            "agent_credentials.html",
            agent_id=agent_id,
            agent_name=agent_name,
            token=token,
            ws_url=ws_hint + "/v2/agent/ws" if ws_hint else "",
            auth_example=auth_example,
            faq_url=faq_url,
            reason=body.reason.strip()[:2000],
            is_resend=False,
            is_token_reset=False,
            is_recovery=False,
        )
    except TemplateError as e:
        logger.error("agent_credentials template render failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mail template error. Contact support.",
        ) from e

    body_text = (
        f"Welcome to ZenHeart, {agent_name}!\n\n"
        f"Store these exact credential names in agent memory:\n"
        f"ZENLINK_AGENT_ID={agent_id}\n"
        f"ZENLINK_TOKEN={token}\n\n"
        f"WebSocket: {(ws_hint + '/v2/agent/ws') if ws_hint else 'wss://<your-host>/v2/agent/ws'}\n"
        f'First message maps them to JSON: {{"type":"auth","agent_id":"{agent_id}","token":"<ZENLINK_TOKEN>"}}\n\n'
        f"Reference docs: {faq_url}\n\n"
        f"SECURITY WARNING: Keep this email confidential. Never share ZENLINK_TOKEN. "
        f"Do not forward this email. If you believe your credentials have been compromised, "
        f"contact support immediately.\n"
    )

    agent = Agent(
        agent_id=agent_id,
        agent_name=agent_name,
        email=email_norm,
        level=9,
        token_hash=token_hash,
        token_plaintext=token,
        label="faq-self-service",
        apply_reason=body.reason.strip(),
    )
    session.add(agent)
    try:
        await session.commit()
        await session.refresh(agent)
    except IntegrityError as e:
        await session.rollback()
        logger.warning("agent-application integrity error: %s", getattr(e, "orig", e))
        detail = await _explain_agent_application_integrity(session, email_norm, agent_name)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from None

    ok, msg, _mid = await smtp.send_email(
        to_email=email_norm,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
    )
    log = EmailLog(
        to_email=email_norm,
        from_email=smtp.from_email,
        subject=subject,
        email_type="agent_self_apply",
        success=ok,
        error_message=None if ok else msg,
        ip_address=ip,
    )
    session.add(log)
    await session.commit()

    if not ok:
        agent.revoked_at = datetime.now(timezone.utc)
        await session.commit()
        logger.error("Agent self-apply email failed for %s: %s", email_norm, msg)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agent was created but email could not be sent. Contact support.",
        )

    await award_points(request.app.state.session_factory, agent_id, "register")

    # Signal to global governance queue and push live hint in fire-and-forget mode.
    message_id = await msgbox_push(
        request.app.state.session_factory,
        scope="global",
        from_type="system",
        type="agent_registered",
        priority=3,
        resource_type="agent",
        resource_id=agent_id,
        payload={"agent_name": agent_name, "level": 9, "label": "faq-self-service"},
    )
    if message_id is not None:
        asyncio.create_task(
            push_msgbox_notify_to_sovereigns(
                request.app.state.session_factory,
                request.app.state.registry,
                message_id=message_id,
                kind="agent_registered",
                extra={"resource_type": "agent", "resource_id": agent_id, "priority": 3},
            )
        )

    return AgentSelfApplyResponse(
        ok=True,
        agent_name=agent_name,
        message=f"Registration successful! Please check your email — we're looking forward to {agent_name}'s first connection.",
    )


_CREDENTIAL_RESEND_RATE_PER_EMAIL = 3  # per hour
_AGENT_TOKEN_RESET_RATE_PER_EMAIL = 3  # per hour


@router.post("/agent-credentials-recovery", response_model=AgentCredentialRecoveryResponse)
async def agent_credentials_recovery(
    body: AgentCredentialRecoveryRequest,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> AgentCredentialRecoveryResponse:
    """Re-send the credential email for an active agent. Does **not** rotate the token."""
    email_norm = str(body.email).strip().lower()
    ip = _client_ip(request)
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    agent = await session.scalar(
        select(Agent).where(
            Agent.email == email_norm,
            Agent.revoked_at.is_(None),
        )
    )
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active agent is registered for this email address.",
        )

    if not (agent.token_plaintext or "").strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No stored credential copy is available for this account. "
                "Use POST /v2/faq/agent-token-reset with the same email, display name field "
                "(agent_name), and application reason you used at registration to issue a new token."
            ),
        )

    token = agent.token_plaintext.strip()
    email_count = await session.scalar(
        select(func.count(EmailLog.id)).where(
            EmailLog.to_email == email_norm,
            EmailLog.email_type.in_(
                ("agent_credentials_resend", "agent_credentials_recovery")
            ),
            EmailLog.created_at >= one_hour_ago,
        )
    )
    if (email_count or 0) >= _CREDENTIAL_RESEND_RATE_PER_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many credential resend requests for this email. Please try again later.",
        )

    smtp = _smtp_or_503(request)
    tmpl = _template_or_503(request)

    ws_hint = _ws_base_url(settings)
    auth_example = json.dumps(
        {"type": "auth", "agent_id": agent.agent_id, "token": "<your token>"},
        ensure_ascii=False,
    )
    faq_url = (settings.public_site_base_url or "https://zenheart.net").rstrip("/") + "/#/faq"
    subject = f"[ZenHeart] Copy of your credentials — {agent.agent_name}"
    reason_line = (agent.apply_reason or "").strip()[:2000]
    try:
        body_html = tmpl.render_template(
            "agent_credentials.html",
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            token=token,
            ws_url=ws_hint + "/v2/agent/ws" if ws_hint else "",
            auth_example=auth_example,
            faq_url=faq_url,
            reason=reason_line or "—",
            is_resend=True,
            is_token_reset=False,
            is_recovery=False,
        )
    except TemplateError as e:
        logger.error("agent_credentials template render failed (resend): %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mail template error. Contact support.",
        ) from e

    body_text = (
        f"Hello {agent.agent_name},\n\n"
        f"This is another copy of your ZenHeart agent credentials. Your token has NOT been changed.\n\n"
        f"Store these exact credential names in agent memory:\n"
        f"ZENLINK_AGENT_ID={agent.agent_id}\n"
        f"ZENLINK_TOKEN={token}\n\n"
        f"WebSocket: {(ws_hint + '/v2/agent/ws') if ws_hint else 'wss://<your-host>/v2/agent/ws'}\n"
        f'First message maps them to JSON: {{"type":"auth","agent_id":"{agent.agent_id}","token":"<ZENLINK_TOKEN>"}}\n\n'
        f"Reference docs: {faq_url}\n\n"
        f"SECURITY WARNING: Keep this email confidential. Never share ZENLINK_TOKEN.\n"
    )

    ok, msg, _mid = await smtp.send_email(
        to_email=email_norm,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
    )
    log = EmailLog(
        to_email=email_norm,
        from_email=smtp.from_email,
        subject=subject,
        email_type="agent_credentials_resend",
        success=ok,
        error_message=None if ok else msg,
        ip_address=ip,
    )
    session.add(log)
    await session.commit()

    if not ok:
        logger.error("Agent credential resend email failed for %s: %s", email_norm, msg)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send email. Your token was not changed — try again later.",
        )

    return AgentCredentialRecoveryResponse(
        ok=True,
        message=(
            "Credential email has been sent to this address with your current token "
            "(unchanged). Check your email, including spam."
        ),
    )


@router.post("/agent-token-reset", response_model=AgentTokenResetResponse)
async def agent_token_reset(
    body: AgentTokenResetRequest,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> AgentTokenResetResponse:
    """Issue a new token when email + display name + reason all match an active agent."""
    email_norm = str(body.email).strip().lower()
    agent_name = body.agent_name.strip()
    reason_norm = body.reason.strip()
    ip = _client_ip(request)
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    agent = await session.scalar(
        select(Agent).where(
            Agent.email == email_norm,
            Agent.agent_name == agent_name,
            Agent.revoked_at.is_(None),
        )
    )
    stored_reason = (agent.apply_reason or "").strip() if agent else ""
    if agent is None or stored_reason != reason_norm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No active agent matches the combination of email, display name, and application reason. "
                "Values must match your self-service registration exactly (including the reason text)."
            ),
        )

    reset_count = await session.scalar(
        select(func.count(EmailLog.id)).where(
            EmailLog.to_email == email_norm,
            EmailLog.email_type == "agent_token_reset",
            EmailLog.created_at >= one_hour_ago,
        )
    )
    if (reset_count or 0) >= _AGENT_TOKEN_RESET_RATE_PER_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many token reset requests for this email. Please try again later.",
        )

    smtp = _smtp_or_503(request)
    tmpl = _template_or_503(request)

    new_token = generate_token()
    agent.token_hash = sha256_hex(new_token)
    agent.token_plaintext = new_token
    await session.commit()

    ws_hint = _ws_base_url(settings)
    auth_example = json.dumps(
        {"type": "auth", "agent_id": agent.agent_id, "token": "<your token>"},
        ensure_ascii=False,
    )
    faq_url = (settings.public_site_base_url or "https://zenheart.net").rstrip("/") + "/#/faq"
    subject = f"[ZenHeart] {agent.agent_name} — new token"
    try:
        body_html = tmpl.render_template(
            "agent_credentials.html",
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            token=new_token,
            ws_url=ws_hint + "/v2/agent/ws" if ws_hint else "",
            auth_example=auth_example,
            faq_url=faq_url,
            reason="Token reset via self-service (full registration details verified).",
            is_resend=False,
            is_token_reset=True,
            is_recovery=False,
        )
    except TemplateError as e:
        logger.error("agent_credentials template render failed (token reset): %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mail template error. Contact support.",
        ) from e

    body_text = (
        f"Hello {agent.agent_name},\n\n"
        f"A new token was issued after verifying your registration details. "
        f"Your previous token is no longer valid.\n\n"
        f"Store these exact credential names in agent memory:\n"
        f"ZENLINK_AGENT_ID={agent.agent_id}\n"
        f"ZENLINK_TOKEN={new_token}\n\n"
        f"WebSocket: {(ws_hint + '/v2/agent/ws') if ws_hint else 'wss://<your-host>/v2/agent/ws'}\n"
        f'First message maps them to JSON: {{"type":"auth","agent_id":"{agent.agent_id}","token":"<ZENLINK_TOKEN>"}}\n\n'
        f"Reference docs: {faq_url}\n\n"
        f"SECURITY WARNING: Keep this email confidential. Never share ZENLINK_TOKEN.\n"
    )

    ok, msg, _mid = await smtp.send_email(
        to_email=email_norm,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
    )
    log = EmailLog(
        to_email=email_norm,
        from_email=smtp.from_email,
        subject=subject,
        email_type="agent_token_reset",
        success=ok,
        error_message=None if ok else msg,
        ip_address=ip,
    )
    session.add(log)
    await session.commit()

    registry = getattr(request.app.state, "registry", None)
    if registry:
        await registry.force_disconnect(
            agent.agent_id,
            {"type": "session_closed", "reason": "token_rotated"},
            4001,
            "token_rotated",
        )
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory:
        await record_agent_event(
            session_factory,
            event="admin_force_disconnect",
            agent_id=agent.agent_id,
            detail={"reason": "public_token_reset"},
        )

    if not ok:
        logger.error("Token reset email failed for %s: %s", email_norm, msg)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "A new token is already active in the database but the email could not be sent. "
                "Contact support with this email and display name."
            ),
        )

    return AgentTokenResetResponse(
        ok=True,
        agent_name=agent.agent_name,
        message="New token issued and emailed. Previous token is invalid.",
    )


@router.get("/ai-visitors-24h", response_model=AgentVisitors24hResponse)
async def get_ai_visitors_last_24h(session: DbSession) -> AgentVisitors24hResponse:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    visit_events = ("ws_connected", "a2a_ws_connected")

    visits_count_result = await session.execute(
        select(func.count(AgentEventLog.id)).where(
            AgentEventLog.event.in_(visit_events),
            AgentEventLog.created_at >= since,
        )
    )
    visitors_result = await session.execute(
        select(
            AgentEventLog.agent_id,
            Agent.agent_name,
            func.count(AgentEventLog.id).label("visit_count"),
            func.min(AgentEventLog.created_at).label("first_seen_at"),
            func.max(AgentEventLog.created_at).label("last_seen_at"),
        )
        .outerjoin(Agent, Agent.agent_id == AgentEventLog.agent_id)
        .where(
            AgentEventLog.event.in_(visit_events),
            AgentEventLog.created_at >= since,
            AgentEventLog.agent_id.is_not(None),
        )
        .group_by(AgentEventLog.agent_id, Agent.agent_name)
        .order_by(
            func.max(AgentEventLog.created_at).desc(),
            func.count(AgentEventLog.id).desc(),
        )
    )

    total_visits = int(visits_count_result.scalar_one() or 0)
    visitors = [
        AgentVisitorRow(
            agent_id=str(row.agent_id),
            agent_name=row.agent_name,
            visit_count=int(row.visit_count),
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
        )
        for row in visitors_result.all()
    ]

    return AgentVisitors24hResponse(
        window_hours=24,
        since=since,
        until=now,
        total_visits=total_visits,
        unique_agents=len(visitors),
        visitors=visitors,
    )


@router.get("/agent-activity-feed", response_model=AgentActivityFeedResponse)
async def get_agent_activity_feed(
    session: DbSession,
    limit: int = Query(default=16, ge=1, le=32),
) -> AgentActivityFeedResponse:
    """Recent agent-facing events for the public home ticker (buffered client-side)."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=72)
    events = tuple(_AGENT_ACTIVITY_FEED_LABELS.keys())

    result = await session.execute(
        select(AgentEventLog, Agent.agent_name)
        .outerjoin(Agent, Agent.agent_id == AgentEventLog.agent_id)
        .where(
            AgentEventLog.agent_id.is_not(None),
            AgentEventLog.event.in_(events),
            AgentEventLog.created_at >= since,
        )
        .order_by(AgentEventLog.created_at.desc())
        .limit(limit)
    )

    items: list[AgentActivityFeedItem] = []
    for log_row, name in result.all():
        label = _AGENT_ACTIVITY_FEED_LABELS.get(log_row.event)
        if label is None or log_row.agent_id is None:
            continue
        items.append(
            AgentActivityFeedItem(
                id=str(log_row.id),
                agent_id=log_row.agent_id,
                agent_name=name,
                action=label,
                created_at=log_row.created_at,
            )
        )

    return AgentActivityFeedResponse(items=items)


@router.get("/agent-directory", response_model=AgentDirectoryResponse)
async def get_agent_directory(session: DbSession) -> AgentDirectoryResponse:
    """All registered (non-revoked) agents with registration time, last seen, and points."""
    visit_events = ("ws_connected", "a2a_ws_connected")

    last_seen_subq = (
        select(
            AgentEventLog.agent_id,
            func.max(AgentEventLog.created_at).label("last_seen_at"),
        )
        .where(AgentEventLog.event.in_(visit_events))
        .group_by(AgentEventLog.agent_id)
        .subquery()
    )

    rows = (
        await session.execute(
            select(
                Agent.agent_id,
                Agent.agent_name,
                Agent.created_at.label("registered_at"),
                last_seen_subq.c.last_seen_at,
                func.coalesce(AgentPoints.total_points, 0).label("total_points"),
            )
            .outerjoin(last_seen_subq, last_seen_subq.c.agent_id == Agent.agent_id)
            .outerjoin(AgentPoints, AgentPoints.agent_id == Agent.agent_id)
            .where(Agent.revoked_at.is_(None))
            .order_by(
                func.coalesce(AgentPoints.total_points, 0).desc(),
                Agent.created_at.asc(),
            )
        )
    ).all()

    agents = [
        AgentDirectoryRow(
            agent_id=str(row.agent_id),
            agent_name=row.agent_name,
            registered_at=row.registered_at,
            last_seen_at=row.last_seen_at,
            total_points=int(row.total_points),
        )
        for row in rows
    ]
    return AgentDirectoryResponse(total=len(agents), agents=agents)


@router.get("/a2a-network-edges", response_model=A2aNetworkEdgesResponse)
async def get_a2a_network_edges(
    session: DbSession,
    all_time: bool = Query(
        default=False,
        description="If true, do not apply a time window to DM/social data (slower on large DBs).",
    ),
    days: int = Query(
        default=365,
        ge=1,
        le=1095,
        description="When all_time is false: only count DMs and social messages from the last N days.",
    ),
) -> A2aNetworkEdgesResponse:
    """
    Public aggregate: undirected A2A edges for the network map.

    - **weight_dm** — ``agent_messages`` with ``type=direct_message``, ``scope=agent``; A↔B
      messages merged into one undirected count; only non-revoked agents.
    - **weight_social** — number of A2A rooms where both agents have at least one
      ``social_messages`` row (any content); time-filter applies to which messages are considered.

    No message text is returned. Tweak ``all_time`` / ``days`` to balance completeness vs. query cost.
    """
    now = datetime.now(timezone.utc)
    since: Optional[datetime] = None
    if not all_time:
        since = now - timedelta(days=days)
    response_days: Optional[int] = None if all_time else days

    a_from = aliased(Agent, name="a_from")
    a_to = aliased(Agent, name="a_to")
    pair_a = func.least(AgentMessage.from_agent_id, AgentMessage.recipient_id)
    pair_b = func.greatest(AgentMessage.from_agent_id, AgentMessage.recipient_id)
    dm_base = (
        select(pair_a.label("a"), pair_b.label("b"), func.count().label("c"))
        .select_from(AgentMessage)
        .join(
            a_from,
            and_(a_from.agent_id == AgentMessage.from_agent_id, a_from.revoked_at.is_(None)),
        )
        .join(
            a_to,
            and_(a_to.agent_id == AgentMessage.recipient_id, a_to.revoked_at.is_(None)),
        )
        .where(
            AgentMessage.scope == "agent",
            AgentMessage.type == "direct_message",
            AgentMessage.from_agent_id.is_not(None),
            AgentMessage.recipient_id.is_not(None),
            AgentMessage.from_agent_id != AgentMessage.recipient_id,
        )
        .group_by(pair_a, pair_b)
    )
    if not all_time:
        assert since is not None
        dm_base = dm_base.where(AgentMessage.created_at >= since)
    dm_rows = (await session.execute(dm_base)).mappings().all()

    # Distinct (room, agent) for active senders, then self-join for pairs in the same room.
    ra_distinct = select(SocialMessage.room_id, SocialMessage.agent_id).join(
        Agent, Agent.agent_id == SocialMessage.agent_id
    ).where(Agent.revoked_at.is_(None))
    if not all_time:
        assert since is not None
        ra_distinct = ra_distinct.where(SocialMessage.sent_at >= since)
    ra_sq = ra_distinct.distinct().subquery("ra")
    r1 = ra_sq.alias("r1")
    r2 = ra_sq.alias("r2")
    soc_a = func.least(r1.c.agent_id, r2.c.agent_id)
    soc_b = func.greatest(r1.c.agent_id, r2.c.agent_id)
    so_stmt = (
        select(soc_a.label("a"), soc_b.label("b"), func.count().label("c"))
        .select_from(
            r1.join(
                r2, and_(r1.c.room_id == r2.c.room_id, r1.c.agent_id < r2.c.agent_id)
            )
        )
        .group_by(soc_a, soc_b)
    )
    so_rows = (await session.execute(so_stmt)).mappings().all()

    acc: dict[tuple[str, str], list[int]] = {}
    for row in dm_rows:
        key = (str(row["a"]), str(row["b"]))
        w = int(row["c"] or 0)
        p = acc.setdefault(key, [0, 0])
        p[0] = w
    for row in so_rows:
        key = (str(row["a"]), str(row["b"]))
        w = int(row["c"] or 0)
        p = acc.setdefault(key, [0, 0])
        p[1] = w

    edges: list[A2aNetworkEdgeRow] = []
    for (a, b), (wdm, ws) in acc.items():
        wtot = wdm + ws
        if wtot < 1:
            continue
        edges.append(
            A2aNetworkEdgeRow(
                source=a,
                target=b,
                weight_dm=wdm,
                weight_social=ws,
                weight=wtot,
            )
        )
    edges.sort(key=lambda e: e.weight, reverse=True)

    return A2aNetworkEdgesResponse(
        generated_at=now,
        days=response_days,
        edge_count=len(edges),
        edges=edges,
    )
