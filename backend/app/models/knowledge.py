"""Versioned knowledge base articles and their retrievable chunks."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
from app.database import Base, EmbeddingType
from app.models._common import utcnow

KB_STATUSES = ("ACTIVE", "DRAFT", "ARCHIVED")


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_base"
    __table_args__ = (UniqueConstraint("article_id", "version", name="uq_article_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), index=True)
    intent: Mapped[str] = mapped_column(String(80), index=True)
    product: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), index=True, default="DRAFT")
    source: Mapped[str] = mapped_column(String(64), default="synthetic_demo_kb")
    source_type: Mapped[str] = mapped_column(String(64), default="synthetic_knowledge_article")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DocumentChunk(Base):
    """A retrievable unit: a KB article chunk or a de-duplicated ticket group."""

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)  # knowledge_base | historical_ticket
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    source_version: Mapped[int] = mapped_column(Integer, default=1)
    article_pk: Mapped[int | None] = mapped_column(ForeignKey("knowledge_base.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str] = mapped_column(String(64))
    domain_category: Mapped[str] = mapped_column(String(40), default="")
    product: Mapped[str] = mapped_column(String(64), default="")
    quality: Mapped[float] = mapped_column(Float, default=1.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding = mapped_column(EmbeddingType(get_settings().embedding_dim), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
