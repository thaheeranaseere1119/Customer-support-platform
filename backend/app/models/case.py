"""A live support case created by each /resolve request."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
from app.database import Base, EmbeddingType
from app.models._common import utcnow


class SupportCase(Base):
    __tablename__ = "support_cases"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(80), index=True)
    request_id: Mapped[str] = mapped_column(String(64))
    complaint: Mapped[str] = mapped_column(Text)
    effective_query: Mapped[str] = mapped_column(Text)
    guided_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_mode: Mapped[str] = mapped_column(String(20), default="free_text")
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    intent: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str] = mapped_column(String(64))
    product: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    sentiment: Mapped[str] = mapped_column(String(16))
    evidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_status: Mapped[str] = mapped_column(String(16), index=True)  # known | uncertain | unknown
    status: Mapped[str] = mapped_column(String(32), index=True)
    current_attempt: Mapped[int] = mapped_column(Integer, default=1)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    used_memory: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    embedding = mapped_column(EmbeddingType(get_settings().embedding_dim), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
