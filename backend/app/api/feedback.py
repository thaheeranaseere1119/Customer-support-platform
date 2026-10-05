from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_container, get_db
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(body: FeedbackRequest, db: Session = Depends(get_db)) -> dict:
    return get_container().pipeline.feedback(db, case_id=body.case_id, outcome=body.outcome,
                                             attempt_number=body.attempt_number, comment=body.comment)
