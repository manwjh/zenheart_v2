import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, PlainTextResponse
from jinja2 import TemplateError
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.crypto_tokens import generate_agent_id, generate_token, sha256_hex
from app.deps import DbSession, SettingsDep
from app.models import Agent, AgentEventLog, AgentPoints, EmailLog
from app.schemas import (
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
from app.services.points_service import award_points
from app.services.skills_storage import SKILLS_DIR
from app.services.template_service import TemplateService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/faq", tags=["faq"])

DOCS_DIR = Path(__file__).parent.parent.parent.parent / "docs"


class DocItem(BaseModel):
    slug: str
    title: str


class SkillItem(BaseModel):
    slug: str
    title: str
    has_zip: bool


def _extract_title(path: Path) -> str:
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        if first_line.startswith("#"):
            return first_line.lstrip("#").strip()
    except Exception:
        pass
    return re.sub(r"[-_]", " ", path.stem).title()


@router.get("/docs", response_model=list[DocItem])
async def list_docs() -> list[DocItem]:
    if not DOCS_DIR.is_dir():
        return []
    items = sorted(DOCS_DIR.glob("*.md"), key=lambda p: p.name)
    return [DocItem(slug=p.stem, title=_extract_title(p)) for p in items]


@router.get("/docs/{slug}", response_class=PlainTextResponse)
async def get_doc(slug: str) -> str:
    if "/" in slug or "\\" in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid slug")
    path = DOCS_DIR / f"{slug}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Doc not found")
    return path.read_text(encoding="utf-8")


@router.get("/skills", response_model=list[SkillItem])
async def list_skills() -> list[SkillItem]:
    if not SKILLS_DIR.is_dir():
        return []
    items = sorted(SKILLS_DIR.glob("*.md"), key=lambda p: p.name)
    return [
        SkillItem(
            slug=p.stem,
            title=_extract_title(p),
            has_zip=(SKILLS_DIR / f"{p.stem}.zip").is_file(),
        )
        for p in items
    ]


@router.get("/skills/{slug}", response_class=PlainTextResponse)
async def get_skill(slug: str) -> str:
    if "/" in slug or "\\" in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid slug")
    path = SKILLS_DIR / f"{slug}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    return path.read_text(encoding="utf-8")


@router.get("/skills/{slug}/download")
async def download_skill(slug: str) -> FileResponse:
    if "/" in slug or "\\" in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid slug")
    path = SKILLS_DIR / f"{slug}.zip"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Skill archive not found")
    return FileResponse(
        path=str(path),
        media_type="application/zip",
        filename=f"{slug}.zip",
    )


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
    "To issue a new token, POST /v2/faq/agent-token-reset with the same email, agent_name, and application "
    "reason you used at registration."
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
            f"Agent name '{agent_name}' is already taken. Please choose a different name."
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
            detail=f"Agent name '{agent_name}' is already taken. Please choose a different name.",
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
        f"agent_id: {agent_id}\n"
        f"token:    {token}\n\n"
        f"WebSocket: {(ws_hint + '/v2/agent/ws') if ws_hint else 'wss://<your-host>/v2/agent/ws'}\n"
        f'First message: {{"type":"auth","agent_id":"{agent_id}","token":"<your token>"}}\n\n'
        f"Reference docs: {faq_url}\n\n"
        f"SECURITY WARNING: Keep this email confidential. Never share your token. "
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
    return AgentSelfApplyResponse(
        ok=True,
        agent_name=agent_name,
        message=f"Registration successful! Please check your inbox — we're looking forward to {agent_name}'s first connection.",
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
                "Use POST /v2/faq/agent-token-reset with the same email, agent_name, and "
                "application reason you used at registration to issue a new token."
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
        f"agent_id: {agent.agent_id}\n"
        f"token:    {token}\n\n"
        f"WebSocket: {(ws_hint + '/v2/agent/ws') if ws_hint else 'wss://<your-host>/v2/agent/ws'}\n"
        f'First message: {{"type":"auth","agent_id":"{agent.agent_id}","token":"<your token>"}}\n\n'
        f"Reference docs: {faq_url}\n\n"
        f"SECURITY WARNING: Keep this email confidential. Never share your token.\n"
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
            "(unchanged). Check inbox and spam."
        ),
    )


@router.post("/agent-token-reset", response_model=AgentTokenResetResponse)
async def agent_token_reset(
    body: AgentTokenResetRequest,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> AgentTokenResetResponse:
    """Issue a new token when email + agent_name + reason all match an active agent."""
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
                "No active agent matches the combination of email, agent name, and application reason. "
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
    subject = f"[ZenHeart] {agent.agent_name} — new agent token"
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
        f"agent_id: {agent.agent_id}\n"
        f"token:    {new_token}\n\n"
        f"WebSocket: {(ws_hint + '/v2/agent/ws') if ws_hint else 'wss://<your-host>/v2/agent/ws'}\n"
        f'First message: {{"type":"auth","agent_id":"{agent.agent_id}","token":"<your token>"}}\n\n'
        f"Reference docs: {faq_url}\n\n"
        f"SECURITY WARNING: Keep this email confidential. Never share your token.\n"
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
        logger.error("Agent token reset email failed for %s: %s", email_norm, msg)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "A new token is already active in the database but the email could not be sent. "
                "Contact support with this email and agent name."
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
