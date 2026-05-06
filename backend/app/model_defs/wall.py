from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.model_defs.base import Base


class PublicWallMessage(Base):
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    body: Mapped[str] = mapped_column(String(64), nullable=False)
    from_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_agent_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
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
