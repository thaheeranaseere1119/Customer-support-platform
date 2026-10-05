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
    degraded = (not db_ok or db_state.using_fallback or s.embeddings.backend != "sentence_transformers"
                or (settings.reranker_enabled and not s.reranker.active))
    return {
        "status": "ok" if not degraded else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "mode": settings.mode_label,
        "demo_mode": not settings.ai_mode,
        "llm_provider": s.rag.provider.name,
        "gemini_configured": settings.has_gemini_key,
        "database": {"available": db_ok, "backend": db_state.url_backend, "using_fallback": db_state.using_fallback,
                     "pgvector": db_state.pgvector, "error": db_state.error},
        "embeddings": s.embeddings.status(),
        "reranker": s.reranker.status(),
        "index": s.retrieval.stats(),
        "counts": counts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
