"""Staff authentication for the admin console and agent APIs.

Customers never log in: the help center and the chat widget use public endpoints. Staff sign in with a
username and password (PBKDF2-SHA256, per-user salt) and receive a signed, expiring bearer token
(HMAC-SHA256 over a small JSON payload), sent as `Authorization: Bearer <token>`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models._common import utcnow
from app.models.staff import StaffUser
from app.utils.errors import AppError

logger = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 310_000
_ephemeral_secret = secrets.token_urlsafe(48)  # development only: tokens stop working when the process restarts
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


class Unauthorized(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class TooManyAttempts(AppError):
    status_code = 429
    code = "TOO_MANY_LOGIN_ATTEMPTS"


# ------------------------------------------------------------------ passwords
def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, _unb64(digest))


# --------------------------------------------------------------------- tokens
def _secret() -> bytes:
    key = get_settings().auth_secret_key
    return (key.get_secret_value() if key else _ephemeral_secret).encode()


def issue_token(user: StaffUser) -> tuple[str, int]:
    expires = int(time.time() + get_settings().auth_token_hours * 3600)
    body = _b64(json.dumps({"sub": user.username, "exp": expires}, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}", expires


def read_token(token: str) -> str:
    """The username in a valid, unexpired token; raises Unauthorized otherwise."""
    try:
        body, signature = token.split(".")
    except ValueError:
        raise Unauthorized("Your session is invalid. Please sign in again.") from None
    if not hmac.compare_digest(signature, _sign(body)):
        raise Unauthorized("Your session is invalid. Please sign in again.")
    try:
        payload = json.loads(_unb64(body))
    except ValueError:
        raise Unauthorized("Your session is invalid. Please sign in again.") from None
    if int(payload.get("exp", 0)) < time.time():
        raise Unauthorized("Your session has expired. Please sign in again.", code="SESSION_EXPIRED")
    return str(payload.get("sub", ""))


def _sign(body: str) -> str:
    return _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------------------------------------------------------------------- login
def authenticate(db: Session, username: str, password: str) -> StaffUser:
    """Check credentials, with a temporary lockout after repeated failures for the same username."""
    settings = get_settings()
    key = username.strip().lower()
    window = settings.auth_lockout_minutes * 60
    now = time.time()
    with _failures_lock:
        recent = [t for t in _failures.get(key, []) if now - t < window]
        _failures[key] = recent
        if len(recent) >= settings.auth_max_failed_logins:
            raise TooManyAttempts("Too many failed sign-in attempts. Please wait a few minutes and try again.")
    user = db.scalar(select(StaffUser).where(func.lower(StaffUser.username) == key))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        with _failures_lock:
            _failures.setdefault(key, []).append(now)
        raise Unauthorized("The username or password is incorrect.", code="INVALID_CREDENTIALS")
    with _failures_lock:
        _failures.pop(key, None)
    user.last_login_at = utcnow()
    return user


def user_for_token(db: Session, token: str) -> StaffUser:
    username = read_token(token)
    user = db.scalar(select(StaffUser).where(StaffUser.username == username))
    if user is None or not user.is_active:
        raise Unauthorized("Your account is not active. Please contact an administrator.")
    return user


def create_user(db: Session, username: str, password: str, display_name: str) -> StaffUser:
    if len(password) < 10:
        raise ValueError("Passwords must be at least 10 characters")
    if db.scalar(select(StaffUser).where(func.lower(StaffUser.username) == username.lower())):
        raise ValueError(f"Staff user {username!r} already exists")
    user = StaffUser(username=username, display_name=display_name, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user


def set_password(db: Session, username: str, password: str) -> StaffUser:
    if len(password) < 10:
        raise ValueError("Passwords must be at least 10 characters")
    user = db.scalar(select(StaffUser).where(func.lower(StaffUser.username) == username.lower()))
    if user is None:
        raise ValueError(f"Staff user {username!r} does not exist")
    user.password_hash = hash_password(password)
    return user


def ensure_first_user(db: Session) -> None:
    """Create the first staff account from ADMIN_USERNAME / ADMIN_PASSWORD while none exists."""
    settings = get_settings()
    if db.scalar(select(func.count()).select_from(StaffUser)):
        return
    if settings.admin_username and settings.admin_password:
        create_user(db, settings.admin_username, settings.admin_password.get_secret_value(), settings.admin_display_name)
        logger.info("Created the first staff account from ADMIN_USERNAME")
    elif settings.auth_enabled:
        logger.warning("No staff account exists: set ADMIN_USERNAME and ADMIN_PASSWORD, or run "
                       "scripts/create_staff_user.py, to sign in to the admin console")


def reset_login_failures() -> None:
    with _failures_lock:
        _failures.clear()
