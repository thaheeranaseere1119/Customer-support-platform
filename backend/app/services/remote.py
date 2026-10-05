"""Gateway-side clients for the internal nlu / retrieval / generation services.

Each adapter subclasses the in-process service and overrides only the work that moves to the other service, so
the pipeline, the evaluation and the admin pages call exactly the same methods whether the system runs as one
process or as separate services.
"""
from __future__ import annotations

import logging
import time

import httpx
import numpy as np
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services import wire
from app.services.classifier import Analysis, ClassificationService
from app.services.llm_provider import LLMProvider
from app.services.rag import RAGAnswer, RAGService
from app.services.reranker import RerankerService
from app.services.retrieval import (
    RetrievalFilters,
    RetrievalOutcome,
    RetrievalService,
    ScoredSource,
)
from app.services.taxonomy import TaxonomySnapshot
from app.utils.errors import RetrievalFailed, ServiceUnavailable

logger = logging.getLogger(__name__)
HEALTH_TTL_SECONDS = 15.0


class ServiceClient:
    """JSON over HTTP to one internal service, authenticated with the shared internal token."""

    def __init__(self, name: str, base_url: str, client: httpx.Client | None = None):
        settings = get_settings()
        token = settings.internal_api_token.get_secret_value() if settings.internal_api_token else ""
        self.name = name
        self.http = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=settings.internal_timeout_seconds)
        self.http.headers["X-Internal-Token"] = token
        self._health: tuple[float, dict] | None = None

    def post(self, path: str, body: dict) -> dict:
        try:
            response = self.http.post(f"/internal/v1{path}", json=body)
        except httpx.HTTPError as exc:
            raise ServiceUnavailable(f"The {self.name} service is unavailable.", code="SERVICE_UNAVAILABLE",
                                     details={"service": self.name, "reason": exc.__class__.__name__}) from None
        if response.status_code != 200:
            raise ServiceUnavailable(f"The {self.name} service returned an error.", code="SERVICE_ERROR",
                                     details={"service": self.name, "status": response.status_code})
        return response.json()

    def health(self) -> dict:
        """Cached health of the service; {"status": "unavailable"} when it cannot be reached."""
        now = time.monotonic()
        if self._health and now - self._health[0] < HEALTH_TTL_SECONDS:
            return self._health[1]
        try:
            response = self.http.get("/internal/v1/health", timeout=5.0)
            data = response.json() if response.status_code == 200 else {"status": "unavailable",
                                                                         "error": f"HTTP {response.status_code}"}
        except httpx.HTTPError as exc:
            data = {"status": "unavailable", "error": exc.__class__.__name__}
        self._health = (now, data)
        return data


class RemoteClassifier(ClassificationService):
    def __init__(self, client: ServiceClient, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.remote = client

    def classify(self, db: Session, text: str, guided_category: str | None = None) -> Analysis:
        return wire.analysis_from(self.remote.post("/classify", {"text": text, "guided_category": guided_category}))


class RemoteRetrieval(RetrievalService):
    """Search runs in the retrieval service; the local index object still serves article indexing bookkeeping."""

    def __init__(self, client: ServiceClient, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.remote = client

    def search(self, db: Session, query: str, *, intent: str | None, category: str | None, product: str | None,
               taxonomy: TaxonomySnapshot, filters: RetrievalFilters | None = None, top_k: int | None = None,
               query_vector: np.ndarray | None = None) -> RetrievalOutcome:
        try:
            data = self.remote.post("/search", {
                "query": query, "intent": intent, "category": category, "product": product,
                "filters": wire.filters_to(filters), "top_k": top_k,
                "query_vector": query_vector.tolist() if query_vector is not None else None})
        except ServiceUnavailable as exc:
            raise RetrievalFailed(exc.message, code="RETRIEVAL_FAILED", details=exc.details) from None
        return wire.outcome_from(data)

    def stats(self) -> dict:
        return self.remote.health().get("index") or {"documents": 0, "service": "unavailable"}


class RemoteReranker(RerankerService):
    def __init__(self, client: ServiceClient):
        super().__init__()
        self.remote = client

    def load(self) -> bool:  # the model lives in the retrieval service
        return self.active

    @property
    def active(self) -> bool:
        return bool((self.remote.health().get("reranker") or {}).get("loaded"))

    def rerank(self, query: str, sources: list[ScoredSource]) -> tuple[list[ScoredSource], str]:
        if not sources:
            return sources, "none"
        try:
            data = self.remote.post("/rerank", {"query": query, "sources": [wire.source_to(s) for s in sources]})
        except ServiceUnavailable:
            logger.warning("Retrieval service unavailable for re-ranking; using the hybrid score")
            for src in sources:
                src.reranker_score, src.final_score = None, src.hybrid_score
            return sorted(sources, key=lambda s: -s.final_score), "hybrid_fallback"
        return [wire.source_from(s) for s in data["sources"]], data["method"]

    def status(self) -> dict:
        return self.remote.health().get("reranker") or {"enabled": True, "loaded": False, "error": "service unavailable"}


class _RemoteProvider(LLMProvider):
    """Describes the generation service's provider for health and labels; generation itself is remote."""

    def __init__(self, client: ServiceClient):
        self.remote = client

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.remote.health().get("llm_provider", "unavailable")

    @property
    def is_llm(self) -> bool:  # type: ignore[override]
        return self.remote.health().get("mode") == "AI MODE"

    def complete_json(self, task: str, system_prompt: str, user_prompt: str, payload: dict) -> dict:
        raise NotImplementedError("generation runs in the generation service")


class RemoteRAG(RAGService):
    """Source selection stays local (cheap, deterministic); drafting and the grounding guard run remotely."""

    def __init__(self, client: ServiceClient):
        super().__init__(_RemoteProvider(client))
        self.remote = client

    @property
    def mode_label(self) -> str:
        return self.remote.health().get("mode", get_settings().mode_label)

    def generate(self, *, sources: list[ScoredSource], **kwargs) -> RAGAnswer:
        try:
            data = self.remote.post("/generate", {**kwargs, "sources": [wire.source_to(s) for s in sources]})
        except ServiceUnavailable:
            # Same safety net as an LLM outage: an evidence-only template, still guarded and cited.
            logger.warning("Generation service unavailable; using the local evidence-only template")
            answer = RAGService(self.fallback).generate(sources=sources, **kwargs)
            answer.generator = "grounded_template_fallback"
            answer.warnings.append("The answer service was unavailable, so a deterministic evidence-only template was used.")
            return answer
        return wire.answer_from(data)
