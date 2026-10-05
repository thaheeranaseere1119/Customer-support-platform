from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._common import utcnow


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    memory: Mapped[dict] = mapped_column(JSON, default=dict)
    customer_name: Mapped[str] = mapped_column(String(80), default="Customer")
    channel: Mapped[str] = mapped_column(String(24), default="agent_console")  # customer_app | agent_console
    # Who is handling the chat: bot -> needs_agent -> agent -> (bot | closed)
    handoff_status: Mapped[str] = mapped_column(String(20), default="bot", index=True)
    handoff_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_agent: Mapped[str | None] = mapped_column(String(80), nullable=True)
    agent_unread: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("conversation_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant (bot) | agent (human) | system
    message: Mapped[str] = mapped_column(Text)
    extra: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
