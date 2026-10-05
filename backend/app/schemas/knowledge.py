from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import StrictModel


class KnowledgeCreate(StrictModel):
    title: str = Field(..., min_length=3, max_length=200)
    content: str = Field(..., min_length=10, max_length=20000)
    category: str = Field(..., min_length=2, max_length=64)
    intent: str = Field(..., min_length=2, max_length=80)
    product: str = Field("", max_length=64)
    status: Literal["ACTIVE", "DRAFT"] = "DRAFT"


class KnowledgeUpdate(StrictModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    content: str | None = Field(None, min_length=10, max_length=20000)
    category: str | None = Field(None, max_length=64)
    intent: str | None = Field(None, max_length=80)
    product: str | None = Field(None, max_length=64)
    status: Literal["ACTIVE", "DRAFT", "ARCHIVED"] | None = None
    change_note: str | None = Field(None, max_length=500)


class ReviewRequest(StrictModel):
    reviewer: str = Field("support-lead", min_length=2, max_length=80)
    notes: str | None = Field(None, max_length=1000)
    title: str | None = Field(None, min_length=3, max_length=200)
    content: str | None = Field(None, min_length=10, max_length=20000)
    intent: str | None = Field(None, max_length=80)
    category: str | None = Field(None, max_length=64)


class KnowledgeArticleOut(BaseModel):
    id: int
    article_id: str
    version: int
    title: str
    content: str
    category: str
    intent: str
    product: str
    status: str
    source: str
    source_type: str
    created_by: str
    change_note: str | None
    is_latest: bool
    created_at: str | None
    updated_at: str | None


class KnowledgeDetailOut(KnowledgeArticleOut):
    versions: list[KnowledgeArticleOut]
    indexed_chunks: int


class KnowledgeListOut(BaseModel):
    items: list[KnowledgeArticleOut]
    total: int
    page: int
    page_size: int


class ReviewResult(BaseModel):
    item_id: str
    status: str
    article: KnowledgeArticleOut | None
    indexed: bool
    index_version: int | None = None
    dataset_record_id: str | None = None
    updated_article: KnowledgeArticleOut | None = None  # existing article that gained the customer's wording
    learned_example: bool = False  # the customer's wording became an example the classifier recognises


class CandidateOut(BaseModel):
    id: str
    case_id: str | None
    origin: str
    complaint: str
    intent: str
    category: str
    product: str
    proposed_title: str
    proposed_resolution: str
    sources: list[dict]
    evidence_score: float
    attempt_number: int
    customer_feedback: str
    occurrences: int
    emerging_signal: bool
    status: str
    reviewer: str | None
    review_notes: str | None
    approved_article_id: str | None
    dataset_record_ids: list[str] = []
    created_at: str | None
    reviewed_at: str | None


class CandidateListOut(BaseModel):
    items: list[CandidateOut]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]
    origin_counts: dict[str, int] = {}
