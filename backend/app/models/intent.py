"""Telecom taxonomy stored in the database (categories, intents, products)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._common import utcnow


class SupportCategory(Base):
    __tablename__ = "support_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    parent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(32), default="signal")
    is_guided: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class IntentTaxonomy(Base):
    __tablename__ = "intent_taxonomy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    domain_category: Mapped[str] = mapped_column(String(40), index=True)
    support_category: Mapped[str] = mapped_column(String(64), index=True)
    default_product: Mapped[str | None] = mapped_column(String(64), nullable=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    example_complaints: Mapped[list] = mapped_column(JSON, default=list)
    clarifying_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    origin: Mapped[str] = mapped_column(String(32), default="dataset")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ProductCatalog(Base):
    __tablename__ = "product_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    support_category: Mapped[str] = mapped_column(String(64))
    keywords: Mapped[list] = mapped_column(JSON, default=list)
