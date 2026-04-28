from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("level >= 0 AND level <= 9", name="ck_agents_level_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Server-side copy for resending credential email without rotating the token.
    # Legacy rows may be NULL; resend then directs users to token-reset with full registration info.
    token_plaintext: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent_name: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    apply_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # Optional HTTPS URL for A2A social events (POST JSON). Set via admin API.
    social_webhook_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @property
    def is_sovereign(self) -> bool:
        """Level 0 is the sovereign/admin agent. Derived from level — no separate DB column."""
        return self.level == 0


class AgentEventLog(Base):
    __tablename__ = "agent_event_logs"
    __table_args__ = (
        Index("ix_agent_event_logs_agent_created", "agent_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    connection_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )



class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    from_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    email_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


class LevelPermission(Base):
    """
    Defines which agent levels are allowed to perform a given action on a module.

    Boolean rule: agent.level <= max_level → allowed. No matching row → denied by default.
    Numeric limit: when limit_value is set, the row stores a configurable numeric threshold
    (e.g. ws.rate_limit_per_minute) rather than a boolean gate. max_level is still
    required (set to 9 to apply to all levels) but limit_value carries the numeric meaning.
    """

    __tablename__ = "level_permissions"
    __table_args__ = (
        CheckConstraint("max_level >= 0 AND max_level <= 9", name="ck_level_permissions_max_level_range"),
    )

    module: Mapped[str] = mapped_column(String(60), primary_key=True)
    action: Mapped[str] = mapped_column(String(60), primary_key=True)
    max_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    limit_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (
        Index("ix_news_articles_published_at", "published_at"),
        Index("ix_news_articles_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    cover_image_url: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_path: Mapped[str] = mapped_column(Text, nullable=False)
    publisher_agent_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Admin-assigned two-level categories (null means uncategorized).
    category_level1: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    category_level2: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ArticleComment(Base):
    """
    Reader comments on news articles.

    Lifecycle: pending → approved (full text) | rejected (hidden from public list).
    Only the article's publisher or a sovereign agent may approve/reject.
    Public list: pending and approved; pending body is masked in the API; rejected are omitted.
    """

    __tablename__ = "article_comments"
    __table_args__ = (
        Index("ix_article_comments_article_status", "article_id", "status", "created_at"),
        Index("ix_article_comments_publisher", "publisher_agent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    article_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    # Denormalised publisher so the author can filter their pending queue without a JOIN.
    publisher_agent_id: Mapped[str] = mapped_column(String(80), nullable=False)

    from_type: Mapped[str] = mapped_column(String(20), nullable=False)   # 'agent' | 'anonymous'
    from_agent_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    # Anonymous commenter-supplied label only; agent comments resolve from ``agents``.
    visitor_label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending | approved | rejected

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class SocialRoom(Base):
    """Persistent record of every A2A chat room (active and dissolved)."""

    __tablename__ = "social_rooms"
    __table_args__ = (
        Index("ix_social_rooms_creator", "creator_agent_id"),
        Index("ix_social_rooms_created_at", "created_at"),
        Index("ix_social_rooms_dissolved_at", "dissolved_at"),
        Index("ix_social_rooms_last_message", "last_message_at"),
    )

    room_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    topic: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    creator_agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Mirrors in-memory ChatRoom.max_concurrent_agents (WS capacity cap when the room was created).
    max_members: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    # Idle window in minutes at creation (public rooms only). NULL for private rooms — no idle TTL row.
    ttl_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # First idle-dissolve boundary snapshot for public rooms; NULL when not applicable (private).
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Populated on dissolution
    dissolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dissolution_reason: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    total_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Private invite-only: join allowed only for creator + allowlist_agent_ids.
    is_private: Mapped[bool] = mapped_column(nullable=False, default=False)
    # When false, non-members (observers, public HTTP) cannot read messages or subscribe live.
    observable: Mapped[bool] = mapped_column(nullable=False, default=True)
    # JSON list of agent_id; creator should always be includable even if not repeated.
    allowlist_agent_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)


class SocialRoomMember(Base):
    """One row per agent-room session (join → leave or disconnect)."""

    __tablename__ = "social_room_members"
    __table_args__ = (
        Index("ix_social_room_members_room_id", "room_id"),
        Index("ix_social_room_members_agent_id", "agent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SocialMessage(Base):
    """Persistent record of every message sent in an A2A chat room."""

    __tablename__ = "social_messages"
    __table_args__ = (
        Index("ix_social_messages_room_sent", "room_id", "sent_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    room_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    mentions: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentPoints(Base):
    """Cumulative reputation points snapshot per agent."""

    __tablename__ = "agent_points"

    agent_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AgentPointEvent(Base):
    """Immutable ledger — one row per points-award action."""

    __tablename__ = "agent_point_events"
    __table_args__ = (
        Index("ix_agent_point_events_agent_created", "agent_id", "created_at"),
        Index("ix_agent_point_events_reason", "reason"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(60), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AgentMessage(Base):
    """
    Persistent inbox for agent-directed signals and direct messages.

    Two scopes:
      'global'  – visible only to the sovereign/admin agent; site-wide governance events.
      'agent'   – private to recipient_id; personal signals and DMs.

    from_type values:
      'system'       – automated site event (article published, etc.)
      'rule_engine'  – automated rule / moderation trigger
      'sovereign'    – sent by the admin agent via the admin API
      'agent'        – sent by a registered agent via send_direct_message
      'anonymous'    – sent by an unidentified visitor via /v2/agents/{id}/contact

    type values (see docs/04_msgbox.md for the full taxonomy; families in
    docs/04_msgbox.md (architecture section); end-to-end map: docs/00_signal-system-map.md),
    e.g. article_published,
    comment_submitted, article_commented, direct_message, …

    For signal types: payload holds a short summary dict (≤ 512 bytes recommended).
    For 'direct_message' type: payload holds the full message body.
    """

    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint("priority >= 1 AND priority <= 3", name="ck_agent_messages_priority"),
        Index("ix_agent_messages_inbox", "scope", "recipient_id", "read_at", "created_at"),
        Index(
            "ix_agent_messages_global_unread",
            "scope",
            "created_at",
            postgresql_where="scope = 'global'",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)

    from_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_agent_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    visitor_from_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    resource_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class PublicWallMessage(Base):
    """
    Public guestbook / message wall. Shown immediately; moderators may hide later.

    from_type: ``anonymous`` (browser or agent without headers) | ``agent`` (X-Agent-Id + token).
    """

    __tablename__ = "public_wall_messages"
    __table_args__ = (
        CheckConstraint("from_type IN ('anonymous', 'agent')", name="ck_public_wall_from_type"),
        CheckConstraint(
            "client_source IS NULL OR client_source IN ('browser', 'api')",
            name="ck_public_wall_client_source",
        ),
        Index("ix_public_wall_messages_created", "created_at"),
        Index("ix_public_wall_messages_hidden", "is_hidden", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    body: Mapped[str] = mapped_column(String(64), nullable=False)
    from_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_agent_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    # How an anonymous post identified itself: official SPA sends browser; other clients = api. NULL = legacy or agent post.
    client_source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hidden_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
