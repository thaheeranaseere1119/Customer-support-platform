from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_container, get_db
from app.schemas.emerging_issue import (
    EmergingIssueOut,
    IntentCreate,
    IntentCreateResult,
    StatusUpdate,
)

router = APIRouter(tags=["emerging-issues"])


@router.get("/emerging-issues", response_model=list[EmergingIssueOut])
def list_issues(status: str | None = Query(None, pattern="^(NEW|UNDER_REVIEW|APPROVED|REJECTED)$"),
                db: Session = Depends(get_db)) -> list[dict]:
    return get_container().services.emerging.list(db, status)


@router.post("/emerging-issues/detect")
def detect(db: Session = Depends(get_db)) -> dict:
    result = get_container().services.emerging.detect(db)
    db.commit()
    return result


@router.get("/emerging-issues/{issue_id}", response_model=EmergingIssueOut)
def get_issue(issue_id: str, db: Session = Depends(get_db)) -> dict:
    return get_container().services.emerging.get(db, issue_id)


@router.post("/emerging-issues/{issue_id}/status", response_model=EmergingIssueOut)
def set_status(issue_id: str, body: StatusUpdate, db: Session = Depends(get_db)) -> dict:
    result = get_container().services.emerging.update_status(db, issue_id, body.status, body.notes)
    db.commit()
    return result


@router.post("/emerging-issues/{issue_id}/create-intent", response_model=IntentCreateResult)
def create_intent(issue_id: str, body: IntentCreate, db: Session = Depends(get_db)) -> dict:
    result = get_container().intents.create_intent(
        db, name=body.name, display_name=body.display_name, description=body.description,
        parent_category=body.parent_category, example_complaints=body.example_complaints, keywords=body.keywords,
        resolution_title=body.resolution_title, resolution_steps=body.resolution_steps,
        domain_category=body.domain_category, clarifying_question=body.clarifying_question, origin="emerging_issue",
        created_by=body.created_by, emerging_issue_id=issue_id)
    db.commit()
    return result
