from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_container, get_db
from app.schemas.emerging_issue import IntentCreate, IntentCreateResult

router = APIRouter(tags=["intents"])


@router.get("/intents")
def list_intents(db: Session = Depends(get_db)) -> dict:
    return get_container().intents.list_intents(db)


@router.post("/intents", response_model=IntentCreateResult, status_code=201)
def create_intent(body: IntentCreate, db: Session = Depends(get_db)) -> dict:
    result = get_container().intents.create_intent(
        db, name=body.name, display_name=body.display_name, description=body.description,
        parent_category=body.parent_category, example_complaints=body.example_complaints, keywords=body.keywords,
        resolution_title=body.resolution_title, resolution_steps=body.resolution_steps,
        domain_category=body.domain_category, clarifying_question=body.clarifying_question, origin="admin",
        created_by=body.created_by)
    db.commit()
    return result
