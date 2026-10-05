"""Service container and FastAPI dependencies."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import db_state, get_sessionmaker
from app.models.staff import StaffUser
from app.services import auth
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
    """In-process services, except where a *_SERVICE_URL points the gateway at a separate service."""
    settings = get_settings()
    embeddings = get_embedding_service()
    llm = get_llm_provider()
    if settings.retrieval_service_url:
        from app.services.remote import RemoteReranker, RemoteRetrieval, ServiceClient
        client = ServiceClient("retrieval", settings.retrieval_service_url)
        retrieval, reranker = RemoteRetrieval(client, embeddings), RemoteReranker(client)
    else:
        retrieval, reranker = RetrievalService(embeddings), RerankerService()
    if settings.nlu_service_url:
        from app.services.remote import RemoteClassifier, ServiceClient
        classifier = RemoteClassifier(ServiceClient("nlu", settings.nlu_service_url), embeddings, llm)
    else:
        classifier = ClassificationService(embeddings, llm)
    if settings.generation_service_url:
        from app.services.remote import RemoteRAG, ServiceClient
        rag = RemoteRAG(ServiceClient("generation", settings.generation_service_url))
    else:
        rag = RAGService(llm)
    knowledge = KnowledgeService(embeddings, retrieval)
    services = Services(
        embeddings=embeddings, reranker=reranker, retrieval=retrieval, evidence=EvidenceScoringService(),
        classifier=classifier, rag=rag, memory=MemoryService(),
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


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def optional_staff(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> StaffUser | None:
    """The signed-in staff member, or None for customers (an invalid token is still rejected)."""
    token = _bearer(authorization)
    return auth.user_for_token(db, token) if token else None


def require_staff(user: StaffUser | None = Depends(optional_staff)) -> StaffUser | None:
    """Admin console and agent endpoints. Returns None only when AUTH_ENABLED=false."""
    if user is None and get_settings().auth_enabled:
        raise auth.Unauthorized("Please sign in to the agent workspace.")
    return user
