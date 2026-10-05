from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import SESSION_PATTERN, StrictModel, clean_user_text


class ResolveRequest(StrictModel):
    session_id: str = Field(..., pattern=SESSION_PATTERN)
    complaint: str = Field(..., min_length=1, max_length=2000)
    guided_category: str | None = Field(None, max_length=64)
    input_mode: Literal["free_text", "guided", "voice"] = "free_text"

    @field_validator("complaint")
    @classmethod
    def _complaint(cls, value: str) -> str:
        value = clean_user_text(value)
        if len(value) < 3:
            raise ValueError("Complaint must contain at least 3 characters")
        return value


class RetryRequest(StrictModel):
    case_id: str = Field(..., min_length=3, max_length=40)
    additional_info: str | None = Field(None, max_length=1000)

    @field_validator("additional_info")
    @classmethod
    def _info(cls, value: str | None) -> str | None:
        return clean_user_text(value) or None if value is not None else None


class Entity(BaseModel):
    type: str
    value: str


class AnalysisOut(BaseModel):
    intent: str
    intent_display: str
    intent_confidence: float
    classification_method: str
    category: str
    subcategory: str | None
    support_category: str
    domain_category: str
    product: str
    severity: Literal["low", "medium", "high", "critical"]
    severity_reasons: list[str]
    sentiment: Literal["positive", "neutral", "negative", "frustrated", "urgent"]
    sentiment_score: float
    entities: list[Entity]
    memory_entities: list[Entity] = []
    candidates: list[dict] = []
    used_memory: bool = False


class SourceOut(BaseModel):
    source_id: str
    source_type: str
    chunk_id: str
    title: str
    excerpt: str
    content: str
    intent: str
    category: str
    product: str
    quality: float
    semantic_raw: float
    semantic_score: float
    keyword_score: float
    metadata_score: float
    hybrid_score: float
    reranker_score: float | None
    final_score: float
    extra: dict = {}


class EvidenceOut(BaseModel):
    score: float
    status: Literal["known", "uncertain", "unknown"]
    components: dict[str, float]
    top_similarity: float
    intent_match: float
    relevant_sources: int
    reasons: list[str]
    thresholds: dict[str, float]


class RetrievalOut(BaseModel):
    evidence_score: float
    evidence: EvidenceOut
    sources: list[SourceOut]
    semantic_used: bool
    keyword_used: bool
    vector_backend: str
    reranker_method: str
    filter_relaxed: bool
    degraded_reasons: list[str]
    candidates_considered: int
    excluded_source_ids: list[str] = []
    latency_ms: float


class StepOut(BaseModel):
    text: str
    citations: list[str]
    kind: Literal["resolution", "information_gathering"]
    already_attempted: bool = False


class ResolutionOut(BaseModel):
    status: Literal["known", "uncertain", "unknown"]
    is_candidate: bool
    label: str
    summary: str
    diagnosis: str
    steps: list[StepOut]
    warnings: list[str]
    escalation: bool
    escalation_reason: str | None
    insufficient_evidence: bool
    follow_up_question: str | None
    generator: str
    guard_report: dict = {}


class CitationOut(BaseModel):
    source_id: str
    source_type: str
    title: str
    excerpt: str
    score: float


class PipelineStage(BaseModel):
    name: str
    label: str
    status: Literal["success", "warning", "error", "skipped"]
    duration_ms: float
    detail: str


class AttemptInfo(BaseModel):
    attempt_number: int
    max_attempts: int
    can_retry: bool


class UnknownIssueOut(BaseModel):
    headline: str
    message: str
    evidence_score: float
    top_similarity: float
    intent_match: float


class MemoryOut(BaseModel):
    summary: str
    used: bool
    state: dict
    turns: int


class ResolveResponse(BaseModel):
    request_id: str
    case_id: str
    session_id: str
    mode: str
    case_status: str
    attempt: AttemptInfo
    analysis: AnalysisOut
    retrieval: RetrievalOut
    resolution: ResolutionOut
    citations: list[CitationOut]
    unknown_issue: UnknownIssueOut | None
    memory: MemoryOut
    pipeline: list[PipelineStage]
    latency_ms: float
