"""Historical support tickets (the 60K dataset or the demo subset)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._common import utcnow


class Ticket(Base):
    __tablename__ = "tickets"

    record_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    dataset_split: Mapped[str] = mapped_column(String(20), index=True)
    customer_complaint: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), index=True)
    intent: Mapped[str] = mapped_column(String(80), index=True)
    product: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    sentiment: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8), default="en")
    interaction_mode: Mapped[str] = mapped_column(String(20), default="free_text")
    channel: Mapped[str] = mapped_column(String(32), default="web")
    entities: Mapped[dict] = mapped_column(JSON, default=dict)
    conversation_context: Mapped[str] = mapped_column(Text, default="")
    previous_troubleshooting: Mapped[str] = mapped_column(Text, default="")
    retrieval_text: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str] = mapped_column(Text)
    resolution_attempt: Mapped[int] = mapped_column(Integer, default=1)
    resolution_status: Mapped[str] = mapped_column(String(20), index=True)
    evidence_status: Mapped[str] = mapped_column(String(20))
    evidence_score: Mapped[float] = mapped_column(Float)
    citation_source_id: Mapped[str] = mapped_column(String(64))
    citation_type: Mapped[str] = mapped_column(String(32))
    customer_feedback: Mapped[str] = mapped_column(String(32))
    human_verification_status: Mapped[str] = mapped_column(String(32))
    knowledge_state: Mapped[str] = mapped_column(String(20), index=True)
    emerging_class_signal: Mapped[str] = mapped_column(String(32))
    escalation_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(64))
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
