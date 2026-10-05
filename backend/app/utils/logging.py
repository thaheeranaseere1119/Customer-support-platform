"""JSON structured logging with secret redaction + persistent system_logs."""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_SECRET_KEYS = re.compile(r"(api[_-]?key|password|secret|token|authorization|passwd|credential)", re.IGNORECASE)
_SECRET_VALUES = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._\-]+)")


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


def redact(value):
    """Recursively remove secrets from log payloads."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SECRET_KEYS.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _SECRET_VALUES.sub("[REDACTED]", value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(redact(extra))
        if record.exc_info:
            payload["exc_info"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", stream=None) -> None:
    root = logging.getLogger()
    if any(getattr(h, "_telecom_json", False) for h in root.handlers):
        root.setLevel(level)
        return
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._telecom_json = True  # type: ignore[attr-defined]
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "urllib3", "sentence_transformers", "transformers", "huggingface_hub", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(event: str, *, level: str = "INFO", db=None, request_id: str | None = None, session_id: str | None = None,
              case_id: str | None = None, **fields) -> None:
    """Log to stdout and (best effort) to the system_logs table."""
    rid = request_id or request_id_var.get()
    clean = redact(fields)
    logging.getLogger("telecom.events").log(
        getattr(logging, level.upper(), logging.INFO), event,
        extra={"fields": {"event": event, "session_id": session_id, "case_id": case_id, **clean}},
    )
    if db is None:
        return
    try:
        from app.models import SystemLog

        db.add(SystemLog(level=level.upper(), event=event, request_id=rid, session_id=session_id, case_id=case_id,
                         payload=json.loads(json.dumps(clean, default=str))))
        db.flush()
    except Exception:  # logging must never break a request
        logging.getLogger(__name__).debug("system_logs write failed", exc_info=True)


def short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
