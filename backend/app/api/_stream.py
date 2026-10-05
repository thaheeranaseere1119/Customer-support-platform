"""NDJSON streaming of live pipeline stages (runs the same pipeline in a worker thread)."""
from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable

from fastapi.responses import StreamingResponse
from sqlalchemy.exc import OperationalError

from app.database import get_sessionmaker
from app.schemas.resolve import ResolveResponse
from app.utils.errors import AppError
from app.utils.logging import request_id_var

logger = logging.getLogger(__name__)
_DONE = object()


def stream_pipeline(request_id: str, run: Callable) -> StreamingResponse:
    events: queue.Queue = queue.Queue()

    def worker() -> None:
        token = request_id_var.set(request_id)
        db = get_sessionmaker()()
        try:
            result = run(db, events.put)
            payload = ResolveResponse.model_validate(result).model_dump(mode="json")
            events.put({"type": "result", "data": payload})
        except AppError as exc:
            db.rollback()
            events.put({"type": "error", "error": {"code": exc.code, "message": exc.message, "request_id": request_id}})
        except OperationalError:
            db.rollback()
            logger.exception("Database error during streamed resolution")
            events.put({"type": "error", "error": {"code": "DATABASE_UNAVAILABLE",
                                                   "message": "The database is currently unavailable.", "request_id": request_id}})
        except Exception:
            db.rollback()
            logger.exception("Unhandled error during streamed resolution")
            events.put({"type": "error", "error": {"code": "RESOLUTION_FAILED",
                                                   "message": "The resolution pipeline failed. Please try again.",
                                                   "request_id": request_id}})
        finally:
            db.close()
            request_id_var.reset(token)
            events.put(_DONE)

    threading.Thread(target=worker, daemon=True, name=f"pipeline-{request_id}").start()

    def generate():
        while True:
            try:
                item = events.get(timeout=180)
            except queue.Empty:
                yield json.dumps({"type": "error", "error": {"code": "TIMEOUT", "message": "The pipeline timed out.",
                                                            "request_id": request_id}}) + "\n"
                return
            if item is _DONE:
                return
            yield json.dumps(item, default=str) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Request-ID": request_id})
