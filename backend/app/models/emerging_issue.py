from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
from app.database import Base, EmbeddingType
from app.models._common import utcnow

EMERGING_STATUSES = ("NEW", "UNDER_REVIEW", "APPROVED", "REJECTED")


class EmergingIssue(Base):
    __tablename__ = "emerging_issues"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    pattern_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), index=True, default="NEW")
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    avg_evidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    example_complaints: Mapped[list] = mapped_column(JSON, default=list)
    suggested_intent_name: Mapped[str] = mapped_column(String(80), default="")
    suggested_category: Mapped[str] = mapped_column(String(64), default="")
    created_intent: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_article_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    centroid = mapped_column(EmbeddingType(get_settings().embedding_dim), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class EmergingIssueMember(Base):
    __tablename__ = "emerging_issue_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    emerging_issue_id: Mapped[str] = mapped_column(ForeignKey("emerging_issues.id", ondelete="CASCADE"), index=True)
    member_type: Mapped[str] = mapped_column(String(20))  # case | candidate
    member_id: Mapped[str] = mapped_column(String(40), index=True)
    complaint: Mapped[str] = mapped_column(Text)
    similarity: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
