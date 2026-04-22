from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import EmailLog
from app.schemas import SendMailWsPayload
from app.services.agent_event_log import record_agent_event
from app.services.permission_service import check_permission
from app.services.smtp_service import SMTPService


async def handle_send_mail_ws_message(
    *,
    smtp_service: Optional[SMTPService],
    session_factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    connection_id: str,
    agent_level: int,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Handle authenticated agent JSON with type send_mail.
    Sends an email via the configured SMTP service.
    Returns a dict to send as one WebSocket text frame (JSON).
    """
    if smtp_service is None:
        return {
            "type": "error",
            "reason": "smtp_not_configured",
            "detail": "Set SMTP_* environment variables to enable mail sending.",
        }

    try:
        payload = SendMailWsPayload.model_validate(data)
    except ValidationError as exc:
        return {
            "type": "error",
            "reason": "invalid_send_mail_payload",
            "detail": exc.errors(),
        }

    # Product policy: WS outbound mail is sovereign (level 0) only, regardless of
    # level_permissions drift. Server/batch mail uses HTTP /v2/mail/* with admin key.
    if agent_level != 0:
        return {
            "type": "error",
            "reason": "forbidden",
            "detail": "send_mail is restricted to sovereign agents (level 0).",
        }

    async with session_factory() as session:
        if not await check_permission(session, "mail", "send", agent_level):
            return {
                "type": "error",
                "reason": "forbidden",
                "detail": "Your level does not have permission to send emails.",
            }

    success, msg, message_id = await smtp_service.send_email(
        to_email=payload.to_email,
        subject=payload.subject,
        body_html=payload.body_html,
        body_text=payload.body_text,
        from_name=payload.from_name,
    )

    async with session_factory() as session:
        log = EmailLog(
            to_email=payload.to_email,
            from_email=smtp_service.from_email,
            subject=payload.subject,
            email_type="agent_ws",
            success=success,
            error_message=None if success else msg,
        )
        session.add(log)
        await session.commit()

    await record_agent_event(
        session_factory,
        event="mail_sent_via_ws",
        agent_id=agent_id,
        connection_id=connection_id,
        detail={
            "to_email": payload.to_email,
            "subject": payload.subject,
            "success": success,
            "message_id": message_id,
            "error": None if success else msg,
        },
    )

    if not success:
        return {
            "type": "error",
            "reason": "smtp_send_failed",
            "detail": msg,
        }

    return {
        "type": "send_mail_ok",
        "to_email": payload.to_email,
        "message_id": message_id,
        "message": "Email sent successfully",
    }
