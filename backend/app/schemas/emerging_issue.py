from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import StrictModel


class EmergingIssueOut(BaseModel):
    id: str
    pattern_name: str
    description: str
    status: str
    occurrences: int
    avg_evidence_score: float
    keywords: list[str]
    example_complaints: list[str]
    suggested_intent_name: str
    suggested_category: str
    created_intent: str | None
    created_article_id: str | None
    review_notes: str | None
    created_at: str | None
    updated_at: str | None
    members: list[dict] | None = None


class StatusUpdate(StrictModel):
    status: Literal["NEW", "UNDER_REVIEW", "REJECTED"]
    notes: str | None = Field(None, max_length=1000)


class IntentCreate(StrictModel):
    name: str = Field(..., min_length=3, max_length=61)
    display_name: str | None = Field(None, max_length=120)
    description: str = Field(..., min_length=5, max_length=1000)
    parent_category: str = Field(..., min_length=2, max_length=64)
    domain_category: str | None = Field(None, max_length=40)
    example_complaints: list[str] = Field(..., min_length=1, max_length=20)
    keywords: list[str] | None = Field(None, max_length=20)
    clarifying_question: str | None = Field(None, max_length=300)
    resolution_title: str | None = Field(None, max_length=200)
    resolution_steps: list[str] | None = Field(None, max_length=12)
    created_by: str = Field("admin", min_length=2, max_length=80)


class IntentCreateResult(BaseModel):
    intent: dict
    article: dict | None
    emerging_issue_id: str | None
    classification_ready: bool
