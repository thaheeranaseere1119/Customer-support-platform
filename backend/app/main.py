"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    analytics,
    conversations,
    emerging_issues,
    feedback,
    health,
    intents,
    knowledge,
    resolve,
    system,
)
from app.config import get_settings
from app.database import create_all, db_state, init_engine, session_scope
from app.dependencies import get_container
from app.utils.errors import AppError, error_body
from app.utils.logging import configure_logging, new_request_id, request_id_var

logger = logging.getLogger("telecom.app")
API_PREFIX = "/api/v1"


def warm_up() -> None:
    """Load models and build the retrieval index so the first request is fast."""
    container = get_container()
    s = container.services
    s.embeddings.load()
    s.reranker.load()
    if db_state.available:
        with session_scope() as db:
            s.retrieval.ensure_index(db)


def bootstrap() -> None:
    settings = get_settings()
    try:
        init_engine()
        create_all()
    except Exception as exc:
        db_state.available = False
        db_state.error = f"Database initialisation failed ({exc.__class__.__name__})"
        logger.error("Database unavailable at startup; API will return DATABASE_UNAVAILABLE errors")
        return
    if settings.auto_seed:
        from app.ingestion import database_is_empty, run_ingestion

        try:
            if database_is_empty():
                logger.info("Empty database detected; seeding (SYNTHETIC / DEMO DATA)")
                summary = run_ingestion()
                logger.info("Seeding complete", extra={"fields": {"summary": summary}})
        except Exception:
            logger.exception("Automatic seeding failed; run scripts/ingest_data.py manually")
    try:  # existing databases pick up new product keywords from data/products.csv
        from app.database import session_scope
        from app.ingestion import sync_products

        with session_scope() as db:
            sync_products(db)
    except Exception:
        logger.exception("Product keyword sync failed")
    try:
        warm_up()
    except Exception:
        logger.exception("Warm-up failed; services will initialise lazily")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging(get_settings().log_level)
    await asyncio.to_thread(bootstrap)
    yield


class BodySizeLimitMiddleware:
    """Pure-ASGI request size limit (works for chunked bodies too)."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            return await self._reject(send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            await self._reject(send)

    async def _reject(self, send):
        response = JSONResponse(status_code=413, content=error_body(
            "PAYLOAD_TOO_LARGE", f"Request body exceeds {self.max_bytes} bytes.", request_id_var.get()))
        await response({"type": "http"}, None, send)


class _TooLarge(Exception):
    pass


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan,
                  docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or new_request_id()
        if len(rid) > 64 or not all(c.isalnum() or c in "-_" for c in rid):
            rid = new_request_id()
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT"], allow_headers=["Content-Type", "X-Request-ID"],
                       expose_headers=["X-Request-ID"])

    def rid(request: Request) -> str | None:
        return getattr(request.state, "request_id", None) or request_id_var.get()

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        if exc.status_code >= 500:
            logger.error("Application error %s: %s", exc.code, exc.message)
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, rid(request), exc.details))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"), "message": e.get("msg", "")}
                  for e in exc.errors()]
        return JSONResponse(status_code=422, content=error_body("VALIDATION_ERROR", "The request is invalid.",
                                                                rid(request), {"fields": fields}))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(status_code=exc.status_code, content=error_body(code, str(exc.detail), rid(request)))

    @app.exception_handler(OperationalError)
    async def db_down(request: Request, exc: OperationalError):
        logger.exception("Database operational error")
        return JSONResponse(status_code=503, content=error_body(
            "DATABASE_UNAVAILABLE", "The database is currently unavailable. Please try again shortly.", rid(request)))

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request: Request, exc: SQLAlchemyError):
        logger.exception("Database error")
        return JSONResponse(status_code=500, content=error_body("DATABASE_ERROR", "A database error occurred.", rid(request)))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error")
        return JSONResponse(status_code=500, content=error_body(
            "INTERNAL_ERROR", "Something went wrong while processing the request.", rid(request)))

    for module in (health, resolve, feedback, knowledge, conversations, emerging_issues, intents, analytics, system):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.get("/")
    def root() -> dict:
        return {"app": settings.app_name, "docs": f"{API_PREFIX}/docs", "health": f"{API_PREFIX}/health"}

    return app


app = create_app()
