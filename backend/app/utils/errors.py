"""Structured application errors. Users never see stack traces."""
from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class OutOfScope(AppError):
    """The message is not a telecom question (or is just a greeting); `message` is the reply to show."""
    status_code = 422
    code = "OUT_OF_SCOPE"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"


class RetrievalFailed(AppError):
    status_code = 502
    code = "RETRIEVAL_FAILED"


def error_body(code: str, message: str, request_id: str | None, details: dict | None = None) -> dict:
    body = {"error": {"code": code, "message": message, "request_id": request_id}}
    if details:
        body["error"]["details"] = details
    return body
