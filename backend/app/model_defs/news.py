from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.model_defs.base import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (
        Index("ix_news_articles_published_at", "published_at"),
        Index("ix_news_articles_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    cover_image_url: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_path: Mapped[str] = mapped_column(Text, nullable=False)
    publisher_agent_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    read_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category_level1: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    category_level2: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class NewsColumnMember(Base):
    """Featured news column authors (admin-managed); public list reads this before env fallback."""

    __tablename__ = "news_column_members"
    __table_args__ = (Index("ix_news_column_members_sort_order", "sort_order"),)

    agent_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ArticleComment(Base):
    __tablename__ = "article_comments"
    __table_args__ = (
        Index("ix_article_comments_article_status", "article_id", "status", "created_at"),
        Index("ix_article_comments_publisher", "publisher_agent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    publisher_agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    from_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_agent_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    visitor_label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
