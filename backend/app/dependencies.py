"""Service container and FastAPI dependencies."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.database import db_state, get_sessionmaker
from app.services.adaptive_resolution import AdaptiveResolutionService, Services
from app.services.classifier import ClassificationService
from app.services.embeddings import get_embedding_service
from app.services.emerging_issue import EmergingIssueService
from app.services.evaluation import EvaluationService
from app.services.evidence import EvidenceScoringService
from app.services.intent_admin import IntentAdminService
from app.services.knowledge_evolution import KnowledgeService
from app.services.llm_provider import get_llm_provider
from app.services.memory import MemoryService
from app.services.rag import RAGService
from app.services.reranker import RerankerService
from app.services.retrieval import RetrievalService
from app.utils.errors import ServiceUnavailable


@dataclass
class Container:
    services: Services
    pipeline: AdaptiveResolutionService
    intents: IntentAdminService
    evaluation: EvaluationService


_container: Container | None = None
_lock = threading.Lock()


def build_container() -> Container:
    embeddings = get_embedding_service()
    retrieval = RetrievalService(embeddings)
    llm = get_llm_provider()
    knowledge = KnowledgeService(embeddings, retrieval)
    services = Services(
        embeddings=embeddings, reranker=RerankerService(), retrieval=retrieval, evidence=EvidenceScoringService(),
        classifier=ClassificationService(embeddings, llm), rag=RAGService(llm), memory=MemoryService(),
        knowledge=knowledge, emerging=EmergingIssueService(embeddings),
    )
    return Container(services=services, pipeline=AdaptiveResolutionService(services),
                     intents=IntentAdminService(knowledge), evaluation=EvaluationService(services))


def get_container() -> Container:
    global _container
    if _container is None:
        with _lock:
            if _container is None:
                _container = build_container()
    return _container


def reset_container() -> None:
    global _container
    _container = None


def get_db() -> Iterator[Session]:
    if not db_state.available:
        raise ServiceUnavailable("The database is currently unavailable. Please try again shortly.",
                                 code="DATABASE_UNAVAILABLE")
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
