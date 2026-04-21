from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class SendEmailRequest(BaseModel):
    to_email: EmailStr
    subject: str = Field(..., min_length=1, max_length=200)
    body_html: str = Field(..., min_length=1, max_length=100_000)
    body_text: Optional[str] = None
    from_name: Optional[str] = None


class SendEmailResponse(BaseModel):
    success: bool
    message: str
    message_id: Optional[str] = None


class MailHealthResponse(BaseModel):
    status: str
    service: str
    version: str
    smtp_connected: bool
    mail_enabled: bool
