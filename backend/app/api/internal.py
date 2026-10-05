"""Internal service APIs, called only by the gateway over the private network (never by browsers).

nlu         POST /internal/v1/classify   complaint -> intent, category, product, severity, sentiment, details
retrieval   POST /internal/v1/search     hybrid semantic + keyword + metadata search over tickets and articles
            POST /internal/v1/rerank     cross-encoder re-ranking of retrieved sources
generation  POST /internal/v1/generate   LLM (or template) draft + grounding guard -> cited steps
all roles   GET  /internal/v1/health
"""
from __future__ import annotations

import hmac
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_container, get_db
from app.services import wire
from app.services.taxonomy import taxonomy_service
from app.utils.errors import AppError

PREFIX = "/internal/v1"


def _container_services():
    return get_container().services


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


def internal_only(x_internal_token: str | None = Header(None)) -> None:
    expected = get_settings().internal_api_token
    if not expected or not x_internal_token or not hmac.compare_digest(x_internal_token, expected.get_secret_value()):
        raise Forbidden("This endpoint is only available to internal services.")


class ClassifyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    guided_category: str | None = Field(None, max_length=64)


class SearchRequest(BaseModel):
    query: str = Field(..., max_length=8000)
    intent: str | None = None
    category: str | None = None
    product: str | None = None
    filters: dict | None = None
    top_k: int | None = Field(None, ge=1, le=100)
    query_vector: list[float] | None = None


class RerankRequest(BaseModel):
    query: str = Field(..., max_length=8000)
    sources: list[dict]


class GenerateRequest(BaseModel):
    complaint: str
    analysis: dict
    mode: str
    sources: list[dict]
    evidence: dict
    memory_summary: str = ""
    troubleshooting: list[str] = []
    customer_context: list[str] = []
    attempt: int = 1
    previous_steps: list[str] = []
    additional_info: str | None = None
    follow_up_question: str | None = None


def health_router(role: str, services: Callable = _container_services) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["internal"], dependencies=[Depends(internal_only)])

    @router.get("/health")
    def health() -> dict:
        s = services()
        data: dict = {"role": role, "status": "ok"}
        if role in ("nlu", "retrieval"):
            data["embeddings"] = s.embeddings.status()
        if role == "retrieval":
            data["reranker"] = s.reranker.status()
            data["index"] = s.retrieval.stats()
        if role in ("nlu", "generation"):
            data["llm_provider"] = s.rag.provider.name
            data["mode"] = get_settings().mode_label
        return data

    return router


def nlu_router(services: Callable = _container_services) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["internal"], dependencies=[Depends(internal_only)])

    @router.post("/classify")
    def classify(body: ClassifyRequest, db: Session = Depends(get_db)) -> dict:
        return services().classifier.classify(db, body.text, body.guided_category).to_dict()

    return router


def retrieval_router(services: Callable = _container_services) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["internal"], dependencies=[Depends(internal_only)])

    @router.post("/search")
    def search(body: SearchRequest, db: Session = Depends(get_db)) -> dict:
        import numpy as np

        vector = np.asarray(body.query_vector, dtype=np.float32) if body.query_vector is not None else None
        outcome = services().retrieval.search(
            db, body.query, intent=body.intent, category=body.category, product=body.product,
            taxonomy=taxonomy_service.get(db), filters=wire.filters_from(body.filters), top_k=body.top_k,
            query_vector=vector)
        return wire.outcome_to(outcome)

    @router.post("/rerank")
    def rerank(body: RerankRequest) -> dict:
        sources, method = services().reranker.rerank(body.query, [wire.source_from(s) for s in body.sources])
        return {"sources": [wire.source_to(s) for s in sources], "method": method}

    return router


def generation_router(services: Callable = _container_services) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["internal"], dependencies=[Depends(internal_only)])

    @router.post("/generate")
    def generate(body: GenerateRequest) -> dict:
        args = body.model_dump()
        args["sources"] = [wire.source_from(s) for s in body.sources]
        return services().rag.generate(**args).to_dict()

    return router


ROLE_ROUTERS = {"nlu": nlu_router, "retrieval": retrieval_router, "generation": generation_router}
