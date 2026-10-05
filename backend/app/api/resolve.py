from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api._stream import stream_pipeline
from app.dependencies import get_container, get_db, require_staff
from app.schemas.resolve import ResolveRequest, ResolveResponse, RetryRequest

router = APIRouter(tags=["resolution"])


@router.post("/resolve", response_model=ResolveResponse, dependencies=[Depends(require_staff)])
def resolve(body: ResolveRequest, db: Session = Depends(get_db)) -> dict:
    return get_container().pipeline.resolve(db, session_id=body.session_id, complaint=body.complaint,
                                            guided_category=body.guided_category, input_mode=body.input_mode)


@router.post("/resolve/stream", dependencies=[Depends(require_staff)])
def resolve_stream(body: ResolveRequest, request: Request, _db: Session = Depends(get_db)):
    pipeline = get_container().pipeline
    return stream_pipeline(request.state.request_id, lambda db, emit: pipeline.resolve(
        db, session_id=body.session_id, complaint=body.complaint, guided_category=body.guided_category,
        input_mode=body.input_mode, on_stage=emit))


@router.post("/resolve/retry", response_model=ResolveResponse)
def retry(body: RetryRequest, db: Session = Depends(get_db)) -> dict:
    return get_container().pipeline.retry(db, case_id=body.case_id, additional_info=body.additional_info)


@router.post("/resolve/retry/stream")
def retry_stream(body: RetryRequest, request: Request, _db: Session = Depends(get_db)):
    pipeline = get_container().pipeline
    return stream_pipeline(request.state.request_id, lambda db, emit: pipeline.retry(
        db, case_id=body.case_id, additional_info=body.additional_info, on_stage=emit))


@router.get("/cases", dependencies=[Depends(require_staff)])
def list_cases(status: str | None = Query(None, max_length=32), evidence_status: str | None = Query(None, max_length=16),
               session_id: str | None = Query(None, max_length=80), limit: int = Query(25, ge=1, le=100),
               offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> dict:
    return get_container().pipeline.list_cases(db, status=status, evidence_status=evidence_status,
                                               session_id=session_id, limit=limit, offset=offset)


@router.get("/cases/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)) -> dict:
    return get_container().pipeline.get_case(db, case_id)
