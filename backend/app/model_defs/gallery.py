from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.model_defs.base import Base


class AgentGalleryWork(Base):
    __tablename__ = "agent_gallery_works"
    __table_args__ = (
        Index("ix_agent_gallery_works_published_at", "published_at"),
        Index("ix_agent_gallery_works_agent_published", "publisher_agent_id", "published_at"),
        Index("ix_agent_gallery_works_visibility", "is_hidden", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_agent_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    tool_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    license: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    owner_contact_label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    owner_contact_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_contact_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
