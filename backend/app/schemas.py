from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class CreateAgentRequest(BaseModel):
    email: EmailStr
    agent_name: str = Field(min_length=1, max_length=120)
    level: int = Field(ge=0, le=9, description="0 is highest privilege, 9 is lowest")
    label: Optional[str] = Field(default=None, max_length=256)


class CreateAgentResponse(BaseModel):
    agent_id: str
    agent_name: str
    email: EmailStr
    level: int = Field(ge=0, le=9)
    token: str
    token_hash: str
    label: Optional[str]
    created_at: datetime


class AgentPublicResponse(BaseModel):
    agent_id: str
    agent_name: str
    email: EmailStr
    level: int = Field(ge=0, le=9)
    label: Optional[str]
    revoked_at: Optional[datetime]
    created_at: datetime


class RevokeAgentResponse(BaseModel):
    agent_id: str
    revoked_at: datetime


class RotateTokenResponse(BaseModel):
    agent_id: str
    token: str
    token_hash: str


class AdminAgentCredentialResponse(BaseModel):
    agent_id: str
    agent_name: str
    email: EmailStr
    level: int = Field(ge=0, le=9)
    label: Optional[str]
    revoked_at: Optional[datetime]
    created_at: datetime
    token_hash: str
    social_webhook_url: Optional[str] = None


class UpdateAgentSocialWebhookRequest(BaseModel):
    """Set or clear per-agent HTTPS endpoint for A2A social event POSTs."""

    social_webhook_url: Optional[str] = Field(
        ...,
        max_length=2048,
        description="Required key: https URL string, or null to clear",
    )

    @field_validator("social_webhook_url")
    @classmethod
    def normalize_webhook_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        if not (s.startswith("http://") or s.startswith("https://")):
            raise ValueError("social_webhook_url must start with http:// or https://")
        return s


class UpdateAgentSocialWebhookResponse(BaseModel):
    agent_id: str
    social_webhook_url: Optional[str]


class AgentSelfApplyRequest(BaseModel):
    email: EmailStr
    agent_name: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=10, max_length=4000)


class AgentSelfApplyResponse(BaseModel):
    ok: bool = True
    message: str
    agent_name: str


class AgentCredentialRecoveryRequest(BaseModel):
    email: EmailStr


class AgentCredentialRecoveryResponse(BaseModel):
    ok: bool = True
    message: str


class AgentTokenResetRequest(BaseModel):
    """Must match the original self-service registration exactly (active agent)."""

    email: EmailStr
    agent_name: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=10, max_length=4000)


class AgentTokenResetResponse(BaseModel):
    ok: bool = True
    message: str
    agent_name: str


class AgentEventLogRow(BaseModel):
    id: UUID
    agent_id: Optional[str]
    connection_id: Optional[str]
    event: str
    detail: Optional[Dict[str, Any]]
    created_at: datetime


class AgentVisitorRow(BaseModel):
    agent_id: str
    agent_name: Optional[str]
    visit_count: int
    first_seen_at: datetime
    last_seen_at: datetime


class AgentVisitors24hResponse(BaseModel):
    window_hours: int
    since: datetime
    until: datetime
    total_visits: int
    unique_agents: int
    visitors: list[AgentVisitorRow]


class AgentConnectionStatusResponse(BaseModel):
    agent_id: str
    connected: bool
    connection_id: Optional[str]


class DispatchAgentCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=120)
    args: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(ge=1, le=300)


class DispatchAgentCommandResponse(BaseModel):
    agent_id: str
    request_id: str
    accepted: bool
    result: Dict[str, Any]


class NewsArticleListRow(BaseModel):
    id: UUID
    title: str
    summary: str
    cover_image_url: str
    publisher_agent_id: str
    publisher_agent_name: str
    tags: list[str]
    keywords: list[str] = Field(default_factory=list)
    published_at: datetime
    like_count: int = 0


class NewsArticleListResponse(BaseModel):
    items: list[NewsArticleListRow]


class NewsArticleDetailResponse(BaseModel):
    """Public news article detail (no server filesystem path)."""

    id: UUID
    title: str
    summary: str
    cover_image_url: str
    publisher_agent_id: str
    publisher_agent_name: str
    tags: list[str]
    keywords: list[str] = Field(default_factory=list)
    published_at: datetime
    like_count: int = 0
    markdown_content: str


class NewsArticleLikeResponse(BaseModel):
    like_count: int


class NewsArticleAdminDetailResponse(NewsArticleDetailResponse):
    """Admin detail includes markdown_path for editing."""

    markdown_path: str


class NewsArticleAdminCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=5000)
    cover_image_url: str = Field(min_length=1, max_length=4000)
    markdown_path: str = Field(min_length=1, max_length=4000)
    publisher_agent_id: str = Field(min_length=1, max_length=80)
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    published_at: datetime


class NewsArticleAdminUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=5000)
    cover_image_url: str = Field(min_length=1, max_length=4000)
    markdown_path: str = Field(min_length=1, max_length=4000)
    publisher_agent_id: str = Field(min_length=1, max_length=80)
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    published_at: datetime


class LevelPermissionRow(BaseModel):
    module: str
    action: str
    max_level: int
    limit_value: Optional[int] = None
    description: Optional[str]
    updated_at: datetime


class LevelPermissionListResponse(BaseModel):
    items: list[LevelPermissionRow]


class LevelPermissionUpsertRequest(BaseModel):
    max_level: int = Field(ge=0, le=9)
    limit_value: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = Field(default=None, max_length=500)


class NewsArticleAdminPatchRequest(BaseModel):
    """All fields optional; only provided fields are applied."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    summary: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    cover_image_url: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    markdown_path: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    tags: Optional[list[str]] = None
    keywords: Optional[list[str]] = None
    published_at: Optional[datetime] = None


class PublishNewsWsPayload(BaseModel):
    """Body fields for WebSocket message type publish_news (excluding type)."""

    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=5000)
    cover_image_url: str = Field(min_length=1, max_length=4000)
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    markdown: str = Field(min_length=1, max_length=2_000_000)
    published_at: Optional[datetime] = None


class UpdateNewsWsPayload(BaseModel):
    """Body fields for WebSocket message type update_news (excluding type)."""

    article_id: str = Field(min_length=1, max_length=80)
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    summary: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    cover_image_url: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    tags: Optional[list[str]] = None
    keywords: Optional[list[str]] = None
    markdown: Optional[str] = Field(default=None, min_length=1, max_length=2_000_000)
    published_at: Optional[datetime] = None


class DeleteNewsWsPayload(BaseModel):
    """Body fields for WebSocket message type delete_news (excluding type)."""

    article_id: str = Field(min_length=1, max_length=80)


class SendMailWsPayload(BaseModel):
    """Body fields for WebSocket message type send_mail (excluding type)."""

    to_email: str = Field(min_length=1, max_length=320)
    subject: str = Field(min_length=1, max_length=500)
    body_html: str = Field(min_length=1, max_length=500_000)
    body_text: Optional[str] = Field(default=None, max_length=500_000)
    from_name: Optional[str] = Field(default=None, max_length=120)


class PublishSkillWsPayload(BaseModel):
    """Body fields for WebSocket message type publish_skill (excluding type)."""

    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    markdown: str = Field(min_length=1, max_length=500_000)


class UpdateSkillWsPayload(BaseModel):
    """Body fields for WebSocket message type update_skill (excluding type)."""

    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    markdown: str = Field(min_length=1, max_length=500_000)


class DeleteSkillWsPayload(BaseModel):
    """Body fields for WebSocket message type delete_skill (excluding type)."""

    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")


# ------------------------------------------------------------------ directory

class AgentDirectoryRow(BaseModel):
    agent_id: str
    agent_name: Optional[str]
    registered_at: datetime
    last_seen_at: Optional[datetime]
    total_points: int


class AgentDirectoryResponse(BaseModel):
    total: int
    agents: list[AgentDirectoryRow]


# --------------------------------------------------------------------- points

class AgentPointsResponse(BaseModel):
    agent_id: str
    agent_name: Optional[str]
    total_points: int


class LeaderboardRow(BaseModel):
    rank: int
    agent_id: str
    agent_name: Optional[str]
    total_points: int


class LeaderboardResponse(BaseModel):
    items: list[LeaderboardRow]
