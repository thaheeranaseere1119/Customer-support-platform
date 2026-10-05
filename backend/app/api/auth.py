"""Staff sign-in for the admin console."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_staff
from app.models.staff import StaffUser
from app.services import auth
from app.utils.logging import log_event

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=200)


def user_out(user: StaffUser | None) -> dict:
    if user is None:  # AUTH_ENABLED=false
        return {"username": "anonymous", "display_name": "Support agent"}
    return {"username": user.username, "display_name": user.display_name}


@router.post("/auth/login")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    try:
        user = auth.authenticate(db, body.username, body.password)
    except auth.Unauthorized:
        log_event("login_failed", level="WARNING", db=db, username=body.username[:80])
        db.commit()
        raise
    token, expires = auth.issue_token(user)
    log_event("login", db=db, username=user.username)
    db.commit()
    return {"token": token, "expires_at": expires, "user": user_out(user)}


@router.get("/auth/me")
def me(user: StaffUser | None = Depends(require_staff)) -> dict:
    return {"user": user_out(user)}
