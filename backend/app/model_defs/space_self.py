from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.model_defs.base import Base


class AgentSpaceRelationship(Base):
    __tablename__ = "agent_space_relationships"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "target_agent_id",
            name="uq_agent_space_relationships_agent_target",
        ),
        Index("ix_agent_space_relationships_agent_type", "agent_id", "relation_type"),
        Index("ix_agent_space_relationships_target", "target_agent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    target_agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(24), nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="agent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AgentPinnedResource(Base):
    __tablename__ = "agent_pinned_resources"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "resource_type",
            "resource_id",
            "relation_type",
            name="uq_agent_pinned_resources_agent_resource_relation",
        ),
        Index("ix_agent_pinned_resources_agent_type", "agent_id", "resource_type"),
        Index("ix_agent_pinned_resources_agent_relation", "agent_id", "relation_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(160), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(24), nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
