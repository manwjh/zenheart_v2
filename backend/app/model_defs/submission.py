from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.model_defs.base import Base


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        CheckConstraint("kind IN ('issue', 'proposal')", name="ck_submissions_kind"),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'changes_requested', 'accepted', 'rejected', 'published')",
            name="ck_submissions_status",
        ),
        CheckConstraint(
            "submitter_type IN ('anonymous', 'human', 'agent', 'system')",
            name="ck_submissions_submitter_type",
        ),
        Index("ix_submissions_status_created", "status", "created_at"),
        Index("ix_submissions_kind_status", "kind", "status"),
        Index("ix_submissions_submitter_agent", "submitter_agent_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    artifact_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    target_slug: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    target_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitter_type: Mapped[str] = mapped_column(String(20), nullable=False)
    submitter_agent_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    submitter_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    submitter_contact: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    reviewer_agent_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    report: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
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
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SubmissionComment(Base):
    __tablename__ = "submission_comments"
    __table_args__ = (
        Index("ix_submission_comments_submission_created", "submission_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    author_type: Mapped[str] = mapped_column(String(20), nullable=False)
    author_agent_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    author_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="public")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class SubmissionReview(Base):
    __tablename__ = "submission_reviews"
    __table_args__ = (
        Index("ix_submission_reviews_submission_created", "submission_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    reviewer_agent_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    owner_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
