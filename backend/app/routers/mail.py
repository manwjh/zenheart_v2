import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import func, select

from app.config import Settings
from app.deps import DbSession, SettingsDep, admin_or_sovereign_guard
from app.mail_schemas import (
    MailHealthResponse,
    SendEmailRequest,
    SendEmailResponse,
)
from app.models import EmailLog
from app.services.smtp_service import SMTPService
from app.services.template_service import TemplateService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/mail", tags=["mail"])


def _smtp(request: Request) -> SMTPService:
    svc = getattr(request.app.state, "smtp_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mail is not configured (set SMTP_* in environment)",
        )
    return svc


def _templates(request: Request) -> TemplateService:
    svc = getattr(request.app.state, "template_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mail templates not initialized",
        )
    return svc


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/health", response_model=MailHealthResponse)
async def mail_health(request: Request, settings: SettingsDep) -> MailHealthResponse:
    smtp = getattr(request.app.state, "smtp_service", None)
    enabled = settings.smtp_configured() and smtp is not None
    smtp_ok = False
    if smtp:
        smtp_ok = await smtp.test_connection()
    return MailHealthResponse(
        status="healthy" if smtp_ok else "degraded",
        service="ZenMail",
        version="2.0.0",
        smtp_connected=smtp_ok,
        mail_enabled=enabled,
    )


@router.post("/send", response_model=SendEmailResponse, dependencies=[Depends(admin_or_sovereign_guard)])
async def send_email(
    body: SendEmailRequest,
    request: Request,
    session: DbSession,
    smtp: SMTPService = Depends(_smtp),
) -> SendEmailResponse:
    success, msg, mid = await smtp.send_email(
        to_email=str(body.to_email),
        subject=body.subject,
        body_html=body.body_html,
        body_text=body.body_text,
        from_name=body.from_name,
    )
    log = EmailLog(
        to_email=str(body.to_email),
        from_email=smtp.from_email,
        subject=body.subject,
        email_type="custom",
        success=success,
        error_message=None if success else msg,
        ip_address=_client_ip(request),
    )
    session.add(log)
    await session.commit()

    if not success:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
    return SendEmailResponse(success=True, message="Email sent successfully", message_id=mid)


@router.get(
    "/stats",
    dependencies=[Depends(admin_or_sovereign_guard)],
)
async def mail_stats(session: DbSession) -> dict[str, int]:
    total = await session.scalar(select(func.count(EmailLog.id)))
    success = await session.scalar(
        select(func.count(EmailLog.id)).where(EmailLog.success.is_(True))
    )
    total = total or 0
    success = success or 0
    failed = total - success
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    recent = await session.scalar(
        select(func.count(EmailLog.id)).where(EmailLog.created_at >= one_day_ago)
    )
    return {
        "total_sent": total,
        "successful": success,
        "failed": failed,
        "last_24h": recent or 0,
    }


def init_mail_app(app: FastAPI, settings: Settings) -> None:
    """Called from lifespan after settings load."""
    if not settings.smtp_configured():
        app.state.smtp_service = None
        app.state.template_service = None
        logger.info("SMTP not configured; /v2/mail send endpoints disabled")
        return

    app.state.smtp_service = SMTPService(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_email=settings.smtp_from_email,
        from_name=settings.smtp_from_name,
        timeout=settings.smtp_timeout_seconds,
    )
    template_dir = Path(__file__).resolve().parent.parent / "templates" / "mail"
    app.state.template_service = TemplateService(template_dir)
    logger.info("Mail (SMTP) initialized for host %s", settings.smtp_host)
