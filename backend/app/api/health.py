from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import func, select

from app.config import get_settings
from app.database import db_state, session_scope
from app.dependencies import get_container
from app.models import KnowledgeArticle, Ticket

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    container = get_container()
    s = container.services
    counts: dict = {}
    db_ok = db_state.available
    if db_ok:
        try:
            with session_scope() as db:
                counts["tickets"] = db.scalar(select(func.count()).select_from(Ticket)) or 0
                counts["active_articles"] = db.scalar(select(func.count()).select_from(KnowledgeArticle).where(
                    KnowledgeArticle.status == "ACTIVE", KnowledgeArticle.is_latest.is_(True))) or 0
        except Exception:
            db_ok = False
    remote = {name: client.health().get("status", "unavailable") for name, client in (
        ("nlu", getattr(s.classifier, "remote", None)), ("retrieval", getattr(s.retrieval, "remote", None)),
        ("generation", getattr(s.rag, "remote", None))) if client is not None}
    mode = getattr(s.rag, "mode_label", settings.mode_label)  # split: the generation service holds the LLM key
    degraded = (not db_ok or db_state.using_fallback or s.embeddings.backend != "sentence_transformers"
                or (settings.reranker_enabled and not s.reranker.active)
                or any(status != "ok" for status in remote.values()))
    return {
        "status": "ok" if not degraded else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "mode": mode,
        "demo_mode": mode != "AI MODE",
        "llm_provider": s.rag.provider.name,
        "gemini_configured": settings.has_gemini_key if not remote.get("generation") else mode == "AI MODE",
        "service_role": settings.service_role,
        "services": remote,
        "database": {"available": db_ok, "backend": db_state.url_backend, "using_fallback": db_state.using_fallback,
                     "pgvector": db_state.pgvector, "error": db_state.error},
        "embeddings": s.embeddings.status(),
        "reranker": s.reranker.status(),
        "index": s.retrieval.stats(),
        "counts": counts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
