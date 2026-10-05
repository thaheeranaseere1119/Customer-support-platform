"""Every resolution attempt is stored; attempts are never overwritten."""
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

from app.database import Base
from app.models._common import utcnow


class ResolutionAttempt(Base):
    __tablename__ = "resolution_attempts"
    __table_args__ = (UniqueConstraint("case_id", "attempt_number", name="uq_case_attempt"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("support_cases.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # known | uncertain | unknown
    is_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str] = mapped_column(Text)
    diagnosis: Mapped[str] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    escalation: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    query: Mapped[str] = mapped_column(Text, default="")
    additional_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    excluded_source_ids: Mapped[list] = mapped_column(JSON, default=list)
    generator: Mapped[str] = mapped_column(String(32), default="template")
    pipeline: Mapped[list] = mapped_column(JSON, default=list)
    retrieval_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    llm_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    total_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
