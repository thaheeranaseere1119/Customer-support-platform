from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_container, get_db, require_staff
from app.models import EvaluationRun
from app.schemas.common import StrictModel
from app.services.analytics import overview
from app.services.evaluation import run_to_dict

router = APIRouter(tags=["analytics"], dependencies=[Depends(require_staff)])


class EvaluateRequest(StrictModel):
    split: str = Field("held_out_test", pattern="^(calibration|held_out_test)$")
    limit: int = Field(60, ge=5, le=500)
    seed: int = Field(7, ge=0, le=10_000)


@router.get("/analytics")
def analytics(db: Session = Depends(get_db)) -> dict:
    data = overview(db)
    data["index"] = get_container().services.retrieval.stats()
    return data


@router.post("/analytics/evaluate")
def evaluate(body: EvaluateRequest, db: Session = Depends(get_db)) -> dict:
    return get_container().evaluation.run(db, split=body.split, limit=body.limit, seed=body.seed)


@router.get("/analytics/evaluations")
def evaluations(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(limit)).all()
    return {"items": [run_to_dict(r) for r in rows]}
