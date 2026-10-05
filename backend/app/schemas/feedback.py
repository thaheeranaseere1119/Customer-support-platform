from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import StrictModel, clean_user_text


class FeedbackRequest(StrictModel):
    case_id: str = Field(..., min_length=3, max_length=40)
    attempt_number: int | None = Field(None, ge=1, le=10)
    outcome: Literal["solved", "partially_solved", "not_solved"]
    comment: str | None = Field(None, max_length=1000)

    @field_validator("comment")
    @classmethod
    def _comment(cls, value: str | None) -> str | None:
        return (clean_user_text(value) or None) if value is not None else None


class FeedbackResponse(BaseModel):
    feedback_id: int
    case_id: str
    attempt_number: int
    outcome: str
    next_action: Literal["closed", "candidate_created", "provide_more_info", "retry", "escalated"]
    message: str
    candidate_id: str | None
    case_status: str
    attempts_remaining: int
