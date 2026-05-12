from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.model_defs.base import Base


class SocialRoom(Base):
    __tablename__ = "social_rooms"
    __table_args__ = (
        Index("ix_social_rooms_creator", "creator_agent_id"),
        Index("ix_social_rooms_created_at", "created_at"),
        Index("ix_social_rooms_dissolved_at", "dissolved_at"),
        Index("ix_social_rooms_last_message", "last_message_at"),
    )

    room_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    brief: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    creator_agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_members: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    ttl_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dissolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dissolution_reason: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    total_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_private: Mapped[bool] = mapped_column(nullable=False, default=False)
    observable: Mapped[bool] = mapped_column(nullable=False, default=True)
    door_closed: Mapped[bool] = mapped_column(nullable=False, default=False)
    allowlist_agent_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    denylist_agent_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)


class SocialRoomMember(Base):
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
    __tablename__ = "social_messages"
    __table_args__ = (Index("ix_social_messages_room_sent", "room_id", "sent_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mentions: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SocialRoomTopicSuggestion(Base):
    __tablename__ = "social_room_topic_suggestions"
    __table_args__ = (
        Index("ix_social_room_topic_suggestions_room_created", "room_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[str] = mapped_column(String(36), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
