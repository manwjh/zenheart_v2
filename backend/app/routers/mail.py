import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import func, select

from app.config import Settings
from app.deps import DbSession, SettingsDep, admin_key_guard
from app.mail_schemas import (
    MailHealthResponse,
    SendEmailRequest,
    SendEmailResponse,
    SendVerificationCodeRequest,
    VerificationCodeResponse,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from app.models import EmailLog, VerificationCode
from app.services.smtp_service import SMTPService
from app.services.template_service import TemplateService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/mail", tags=["mail"])

_PURPOSE_SUBJECT: dict[str, dict[str, str]] = {
    "zh": {
        "login": "登录验证码",
        "register": "注册验证码",
        "reset_password": "密码重置验证码",
    },
    "en": {
        "login": "Login Verification Code",
        "register": "Registration Verification Code",
        "reset_password": "Password Reset Code",
    },
    "ja": {
        "login": "ログイン認証コード",
        "register": "登録認証コード",
        "reset_password": "パスワードリセットコード",
    },
    "ko": {
        "login": "로그인 인증 코드",
        "register": "등록 인증 코드",
        "reset_password": "비밀번호 재설정 코드",
    },
    "zh-tw": {
        "login": "登入驗證碼",
        "register": "註冊驗證碼",
        "reset_password": "密碼重置驗證碼",
    },
}

_PURPOSE_BODY: dict[str, dict[str, str]] = {
    "zh": {
        "login": "登录",
        "register": "注册",
        "reset_password": "重置密码",
    },
    "en": {
        "login": "Login",
        "register": "Registration",
        "reset_password": "Password Reset",
    },
    "ja": {
        "login": "ログイン",
        "register": "登録",
        "reset_password": "パスワードリセット",
    },
    "ko": {
        "login": "로그인",
        "register": "등록",
        "reset_password": "비밀번호 재설정",
    },
    "zh-tw": {
        "login": "登入",
        "register": "註冊",
        "reset_password": "重設密碼",
    },
}

_BRAND_PREFIX: dict[str, str] = {
    "zh": "【禅心】",
    "en": "[ZenHeart] ",
    "ja": "【禅心】",
    "ko": "[젠하트] ",
    "zh-tw": "【禪心】",
}


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


async def _check_rate_limit(
    session,
    settings: Settings,
    email: str,
    ip: str,
    language: str,
) -> tuple[bool, str]:
    per_email = settings.mail_rate_limit_per_email
    per_ip = settings.mail_rate_limit_per_ip
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    q_email = await session.execute(
        select(func.count(VerificationCode.id)).where(
            VerificationCode.email == email,
            VerificationCode.created_at >= one_hour_ago,
        )
    )
    email_count = q_email.scalar_one()
    if email_count >= per_email:
        messages = {
            "zh": f"该邮箱验证码发送次数已达上限（每小时{per_email}次），请稍后再试",
            "zh-tw": f"該郵箱驗證碼發送次數已達上限（每小時{per_email}次），請稍後再試",
            "en": f"Verification code sending limit reached ({per_email} times per hour), please try again later",
            "ja": f"認証コードの送信回数が上限に達しました（1時間に{per_email}回）、しばらくしてから再試行してください",
            "ko": f"인증 코드 전송 횟수가 한도에 도달했습니다（시간당 {per_email}회）, 나중에 다시 시도해 주세요",
        }
        return False, messages.get(language, messages["en"])

    q_ip = await session.execute(
        select(func.count(VerificationCode.id)).where(
            VerificationCode.ip_address == ip,
            VerificationCode.created_at >= one_hour_ago,
        )
    )
    ip_count = q_ip.scalar_one()
    if ip_count >= per_ip:
        messages = {
            "zh": f"发送次数过多（每小时{per_ip}次），请稍后再试",
            "zh-tw": f"發送次數過多（每小時{per_ip}次），請稍後再試",
            "en": f"Too many requests ({per_ip} times per hour), please try again later",
            "ja": f"リクエストが多すぎます（1時間に{per_ip}回）、しばらくしてから再試行してください",
            "ko": f"너무 많은 요청（시간당 {per_ip}회）, 나중에 다시 시도해 주세요",
        }
        return False, messages.get(language, messages["en"])

    return True, ""


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


@router.post("/send", response_model=SendEmailResponse)
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


@router.post("/send-verification-code", response_model=VerificationCodeResponse)
async def send_verification_code(
    body: SendVerificationCodeRequest,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
    smtp: SMTPService = Depends(_smtp),
    tmpl: TemplateService = Depends(_templates),
) -> VerificationCodeResponse:
    lang = body.language if body.language in _PURPOSE_SUBJECT else "zh"
    allowed, err_msg = await _check_rate_limit(
        session, settings, str(body.to_email), _client_ip(request), lang
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=err_msg)

    code = tmpl.generate_verification_code(
        settings.verification_code_length,
        "numeric",
    )
    expire_sec = settings.verification_code_expire_seconds
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expire_sec)

    subject_key = _PURPOSE_SUBJECT[lang]
    subject = subject_key.get(body.purpose, "Verification Code")
    brand = _BRAND_PREFIX.get(lang, "【禅心】")
    purpose_label = _PURPOSE_BODY.get(lang, _PURPOSE_BODY["zh"]).get(
        body.purpose, body.purpose
    )

    body_html = tmpl.render_template(
        "verification_code.html",
        code=code,
        expires_minutes=max(1, expire_sec // 60),
        purpose=purpose_label,
        language=lang,
    )

    success, msg, _mid = await smtp.send_email(
        to_email=str(body.to_email),
        subject=f"{brand}{subject}",
        body_html=body_html,
    )

    client_ip = _client_ip(request)
    email_log = EmailLog(
        to_email=str(body.to_email),
        from_email=smtp.from_email,
        subject=f"{brand}{subject}",
        email_type="verification_code",
        success=success,
        error_message=None if success else msg,
        ip_address=client_ip,
    )
    session.add(email_log)

    if not success:
        await session.commit()
        low = msg.lower()
        if "not verified" in low or "identities failed" in low:
            friendly = {
                "zh": "ZenHeart 服务繁忙，请稍后再试",
                "zh-tw": "ZenHeart 服務繁忙，請稍後再試",
                "en": "ZenHeart is busy, please try again later",
                "ja": "ZenHeart は混雑しています。しばらくしてからもう一度お試しください",
                "ko": "ZenHeart가 혼잡합니다. 나중에 다시 시도해 주세요",
            }
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=friendly.get(lang, friendly["en"]),
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send email, please try again later",
        )

    session.add(
        VerificationCode(
            email=str(body.to_email),
            code=code,
            purpose=body.purpose,
            expires_at=expires_at,
            ip_address=client_ip,
        )
    )
    await session.commit()

    return VerificationCodeResponse(
        success=True,
        message="Verification code sent, please check your email",
        expires_at=expires_at,
    )


@router.post("/verify-code", response_model=VerifyCodeResponse)
async def verify_code(body: VerifyCodeRequest, session: DbSession) -> VerifyCodeResponse:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(VerificationCode).where(
            VerificationCode.email == str(body.email),
            VerificationCode.code == body.code,
            VerificationCode.purpose == body.purpose,
            VerificationCode.is_used.is_(False),
            VerificationCode.expires_at > now,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return VerifyCodeResponse(
            success=True,
            valid=False,
            message="Verification code is invalid or expired",
        )

    row.is_used = True
    row.used_at = now
    await session.commit()

    return VerifyCodeResponse(
        success=True,
        valid=True,
        message="Verification code accepted",
    )


@router.get(
    "/stats",
    dependencies=[Depends(admin_key_guard)],
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
