from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies import get_container, get_db
from app.models import CandidateCase
from app.schemas.knowledge import (
    CandidateListOut,
    KnowledgeArticleOut,
    KnowledgeCreate,
    KnowledgeDetailOut,
    KnowledgeListOut,
    KnowledgeUpdate,
    ReviewRequest,
    ReviewResult,
)
from app.services.knowledge_evolution import article_to_dict

router = APIRouter(tags=["knowledge"])


def _knowledge():
    return get_container().services.knowledge


@router.get("/knowledge", response_model=KnowledgeListOut)
def list_knowledge(status: str | None = Query(None, pattern="^(ACTIVE|DRAFT|ARCHIVED|active|draft|archived)$"),
                   category: str | None = Query(None, max_length=64), intent: str | None = Query(None, max_length=80),
                   q: str | None = Query(None, max_length=120), page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    items, total = _knowledge().list_articles(db, status=status, category=category, intent=intent, q=q, page=page,
                                              page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/candidates", response_model=CandidateListOut)
def list_candidates(status: str | None = Query(None, pattern="^(pending_review|approved|rejected)$"),
                    origin: str | None = Query(None, pattern="^(live_feedback|kb_match|agent_resolved|dataset|demo_seed)$"),
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                    db: Session = Depends(get_db)) -> dict:
    items, total = _knowledge().list_candidates(db, status=status, origin=origin, page=page, page_size=page_size)
    counts = dict(db.execute(select(CandidateCase.status, func.count()).group_by(CandidateCase.status)).all())
    origin_counts = dict(db.execute(select(CandidateCase.origin, func.count()).group_by(CandidateCase.origin)).all())
    return {"items": items, "total": total, "page": page, "page_size": page_size, "counts": counts,
            "origin_counts": origin_counts}


@router.get("/knowledge/{article_id}", response_model=KnowledgeDetailOut)
def get_knowledge(article_id: str, db: Session = Depends(get_db)) -> dict:
    return _knowledge().get_article(db, article_id)


@router.post("/knowledge", response_model=KnowledgeArticleOut, status_code=201)
def create_knowledge(body: KnowledgeCreate, db: Session = Depends(get_db)) -> dict:
    article = _knowledge().create_article(db, title=body.title, content=body.content, category=body.category,
                                          intent=body.intent, product=body.product, status=body.status)
    db.commit()
    return article_to_dict(article)


@router.put("/knowledge/{article_id}", response_model=KnowledgeArticleOut)
def update_knowledge(article_id: str, body: KnowledgeUpdate, db: Session = Depends(get_db)) -> dict:
    article = _knowledge().update_article(db, article_id, body.model_dump(exclude_none=True))
    db.commit()
    return article_to_dict(article)


def _with_index_version(db: Session, result: dict) -> dict:
    retrieval = get_container().services.retrieval
    retrieval.ensure_index(db)
    result["index_version"] = retrieval.version
    return result


@router.post("/knowledge/{item_id}/approve", response_model=ReviewResult)
def approve(item_id: str, body: ReviewRequest, db: Session = Depends(get_db)) -> dict:
    result = _knowledge().approve(db, item_id, reviewer=body.reviewer, notes=body.notes, title=body.title,
                                  content=body.content, intent=body.intent, category=body.category)
    db.commit()
    return _with_index_version(db, result)


@router.post("/knowledge/{item_id}/reject", response_model=ReviewResult)
def reject(item_id: str, body: ReviewRequest, db: Session = Depends(get_db)) -> dict:
    result = _knowledge().reject(db, item_id, reviewer=body.reviewer, notes=body.notes)
    db.commit()
    return _with_index_version(db, result)
