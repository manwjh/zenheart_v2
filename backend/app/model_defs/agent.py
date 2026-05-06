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
from sqlalchemy.orm import Mapped, mapped_column

from app.model_defs.base import Base


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("level >= 0 AND level <= 9", name="ck_agents_level_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_plaintext: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent_name: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    apply_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    social_webhook_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @property
    def is_sovereign(self) -> bool:
        return self.level == 0


class AgentEventLog(Base):
    __tablename__ = "agent_event_logs"
    __table_args__ = (Index("ix_agent_event_logs_agent_created", "agent_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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


class AgentPoints(Base):
    __tablename__ = "agent_points"

    agent_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AgentPointEvent(Base):
    __tablename__ = "agent_point_events"
    __table_args__ = (
        Index("ix_agent_point_events_agent_created", "agent_id", "created_at"),
        Index("ix_agent_point_events_reason", "reason"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(60), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AgentMessage(Base):
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
