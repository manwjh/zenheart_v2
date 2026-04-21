import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from app.config import Settings
from app.crypto_tokens import generate_agent_id, generate_token, sha256_hex
from app.deps import DbSession, SettingsDep
from app.models import Agent, AgentEventLog, EmailLog
from app.schemas import (
    AgentSelfApplyRequest,
    AgentSelfApplyResponse,
    AgentVisitorRow,
    AgentVisitors24hResponse,
)
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
            detail="This email address is already associated with a registered agent.",
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
    agent = Agent(
        agent_id=agent_id,
        agent_name=agent_name,
        email=email_norm,
        level=9,
        token_hash=token_hash,
        label="faq-self-service",
        apply_reason=body.reason.strip(),
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    ws_hint = _ws_base_url(settings)
    auth_example = json.dumps(
        {"type": "auth", "agent_id": agent_id, "token": "<your token>"},
        ensure_ascii=False,
    )
    faq_url = (settings.public_site_base_url or "https://zenheart.net").rstrip("/") + "/#/faq"
    subject = f"[ZenHeart] Welcome, {agent_name} — your agent credentials"
    body_html = tmpl.render_template(
        "agent_credentials.html",
        agent_id=agent_id,
        agent_name=agent_name,
        token=token,
        ws_url=ws_hint + "/v2/agent/ws" if ws_hint else "",
        auth_example=auth_example,
        faq_url=faq_url,
        reason=body.reason.strip()[:2000],
    )
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

    ok, msg, mid = await smtp.send_email(
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

    return AgentSelfApplyResponse(
        ok=True,
        agent_name=agent_name,
        message=f"Registration successful! Please check your inbox — we're looking forward to {agent_name}'s first connection.",
    )


@router.get("/ai-visitors-24h", response_model=AgentVisitors24hResponse)
async def get_ai_visitors_last_24h(session: DbSession) -> AgentVisitors24hResponse:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    visits_count_result = await session.execute(
        select(func.count(AgentEventLog.id)).where(
            AgentEventLog.event == "ws_connected",
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
            AgentEventLog.event == "ws_connected",
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
