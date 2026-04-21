from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class SendEmailRequest(BaseModel):
    to_email: EmailStr
    subject: str = Field(..., min_length=1, max_length=200)
    body_html: str = Field(..., min_length=1)
    body_text: Optional[str] = None
    from_name: Optional[str] = None


class SendVerificationCodeRequest(BaseModel):
    to_email: EmailStr
    purpose: str = Field(default="login", pattern="^(login|register|reset_password)$")
    language: str = Field(default="zh", pattern="^(zh|en|ja|ko|zh-tw)$")


class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=8)
    purpose: str = Field(default="login", pattern="^(login|register|reset_password)$")


class SendEmailResponse(BaseModel):
    success: bool
    message: str
    message_id: Optional[str] = None


class VerificationCodeResponse(BaseModel):
    success: bool
    message: str
    expires_at: Optional[datetime] = None


class VerifyCodeResponse(BaseModel):
    success: bool
    valid: bool
    message: str


class MailHealthResponse(BaseModel):
    status: str
    service: str
    version: str
    smtp_connected: bool
    mail_enabled: bool
