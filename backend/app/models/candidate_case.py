"""Candidate knowledge awaiting human verification.

Customer "solved" feedback only ever creates a row here; it never becomes trusted
knowledge until a reviewer approves it.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
from app.database import Base, EmbeddingType
from app.models._common import utcnow

CANDIDATE_STATUSES = ("pending_review", "approved", "rejected")


class CandidateCase(Base):
    __tablename__ = "candidate_cases"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("support_cases.id", ondelete="SET NULL"), nullable=True, index=True)
    origin: Mapped[str] = mapped_column(String(32), default="live_feedback")  # live_feedback | kb_match | agent_resolved | dataset | demo_seed
    complaint: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str] = mapped_column(String(64))
    product: Mapped[str] = mapped_column(String(64), default="")
    proposed_title: Mapped[str] = mapped_column(String(200))
    proposed_resolution: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    evidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    customer_feedback: Mapped[str] = mapped_column(String(32), default="not_collected")
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    dataset_record_ids: Mapped[list] = mapped_column(JSON, default=list)
    emerging_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), index=True, default="pending_review")
    reviewer: Mapped[str | None] = mapped_column(String(80), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_article_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    embedding = mapped_column(EmbeddingType(get_settings().embedding_dim), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
