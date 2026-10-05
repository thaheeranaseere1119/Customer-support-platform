"""Settings (non-secret, runtime-tunable subset) and system logs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import RUNTIME_TUNABLE, get_settings, update_runtime_settings
from app.dependencies import get_container, get_db
from app.models import SystemLog
from app.schemas.common import StrictModel
from app.utils.errors import ValidationFailed
from app.utils.logging import log_event

router = APIRouter(tags=["system"])


class SettingsUpdate(StrictModel):
    known_threshold: float | None = Field(None, ge=0, le=1)
    unknown_threshold: float | None = Field(None, ge=0, le=1)
    semantic_weight: float | None = Field(None, ge=0, le=1)
    keyword_weight: float | None = Field(None, ge=0, le=1)
    metadata_weight: float | None = Field(None, ge=0, le=1)
    top_k: int | None = Field(None, ge=1, le=50)
    max_resolution_attempts: int | None = Field(None, ge=1, le=10)
    reranker_enabled: bool | None = None
    emerging_similarity_threshold: float | None = Field(None, ge=0.3, le=0.99)
    emerging_min_cluster_size: int | None = Field(None, ge=2, le=1000)


def settings_payload() -> dict:
    s = get_settings()
    c = get_container().services
    return {
        "mode": s.mode_label, "demo_mode": not s.ai_mode, "app_env": s.app_env,
        "llm": {"provider": c.rag.provider.name, "gemini_model": s.gemini_model, "gemini_configured": s.has_gemini_key},
        "embedding": {"model": s.embedding_model, "backend": c.embeddings.backend, "dimension": s.embedding_dim},
        "reranker": {"model": s.reranker_model, "enabled": s.reranker_enabled, "loaded": c.reranker.active},
        "tunable": {k: getattr(s, k) for k in RUNTIME_TUNABLE},
        "evidence_weights": {"semantic": s.evidence_semantic_weight, "reranker": s.evidence_reranker_weight,
                             "intent_match": s.evidence_intent_weight, "source_quality": s.evidence_source_quality_weight,
                             "metadata": s.evidence_metadata_weight},
        "limits": {"max_complaint_chars": s.max_complaint_chars, "max_request_bytes": s.max_request_bytes,
                   "memory_max_messages": s.memory_max_messages, "memory_max_chars": s.memory_max_chars},
    }


@router.get("/settings")
def read_settings() -> dict:
    return settings_payload()


@router.put("/settings")
def write_settings(body: SettingsUpdate) -> dict:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise ValidationFailed("No settings supplied")
    if {"semantic_weight", "keyword_weight", "metadata_weight"} & changes.keys():
        current = get_settings()
        for key in ("semantic_weight", "keyword_weight", "metadata_weight"):
            changes.setdefault(key, getattr(current, key))
    try:
        update_runtime_settings(changes)
    except ValueError as exc:
        raise ValidationFailed(str(exc).split("\n")[-1].strip() or "Invalid settings") from None
    log_event("settings_updated", changed=sorted(changes))
    return settings_payload()


@router.get("/logs")
def logs(limit: int = Query(50, ge=1, le=200), event: str | None = Query(None, max_length=64),
         db: Session = Depends(get_db)) -> dict:
    stmt = select(SystemLog).order_by(SystemLog.id.desc()).limit(limit)
    if event:
        stmt = stmt.where(SystemLog.event == event)
    return {"items": [{"id": r.id, "created_at": r.created_at.isoformat(), "level": r.level, "event": r.event,
                       "request_id": r.request_id, "session_id": r.session_id, "case_id": r.case_id,
                       "payload": r.payload} for r in db.scalars(stmt)]}
