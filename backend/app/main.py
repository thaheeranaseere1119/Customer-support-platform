"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    analytics,
    auth,
    conversations,
    emerging_issues,
    feedback,
    health,
    intents,
    knowledge,
    resolve,
    system,
)
from app.api.internal import ROLE_ROUTERS, health_router
from app.config import get_settings
from app.database import create_all, db_state, init_engine, session_scope
from app.dependencies import get_container
from app.utils.errors import AppError, error_body
from app.utils.logging import configure_logging, new_request_id, request_id_var

logger = logging.getLogger("telecom.app")
API_PREFIX = "/api/v1"


INTERNAL_MAX_REQUEST_BYTES = 4 * 1024 * 1024  # internal calls carry retrieved documents and query vectors


def warm_up(role: str) -> None:
    """Load what this role uses and build the retrieval index so the first request is fast."""
    s = get_container().services
    if role == "generation":
        return  # the LLM client is created per request; no models or database
    s.embeddings.load()
    if role in ("all", "retrieval"):
        s.reranker.load()
    if role in ("all", "gateway", "retrieval") and db_state.available:
        with session_scope() as db:
            s.retrieval.ensure_index(db)


def bootstrap(role: str) -> None:
    """Start-up work for this role. Only the gateway (or the all-in-one process) seeds data and creates accounts."""
    settings = get_settings()
    if role == "generation":
        warm_up(role)
        return
    try:
        init_engine()
        create_all()
    except Exception as exc:
        db_state.available = False
        db_state.error = f"Database initialisation failed ({exc.__class__.__name__})"
        logger.error("Database unavailable at startup; API will return DATABASE_UNAVAILABLE errors")
        return
    if role in ("nlu", "retrieval"):
        try:
            warm_up(role)
        except Exception:
            logger.exception("Warm-up failed; services will initialise lazily")
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
        from app.ingestion import sync_intent_keywords, sync_products

        with session_scope() as db:
            sync_products(db)
            sync_intent_keywords(db)
    except Exception:
        logger.exception("Product keyword sync failed")
    try:  # existing databases pick up seed article updates (customer wording) from data/knowledge_base.csv
        from app.ingestion import sync_seed_articles

        with session_scope() as db:
            result = sync_seed_articles(db, get_container().services.knowledge, Path(settings.knowledge_base_path))
            if any(result.values()):
                logger.info("Seed articles synced", extra={"fields": result})
    except Exception:
        logger.exception("Seed article sync failed")
    try:
        from app.services.auth import ensure_first_user

        with session_scope() as db:
            ensure_first_user(db)
    except Exception:
        logger.exception("Could not create the first staff account")
    try:
        warm_up(role)
    except Exception:
        logger.exception("Warm-up failed; services will initialise lazily")


def make_lifespan(role: str):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        configure_logging(get_settings().log_level)
        await asyncio.to_thread(bootstrap, role)
        yield

    return lifespan


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


def create_app(role: str | None = None, services=None) -> FastAPI:
    """The gateway / all-in-one API, or one internal service (nlu, retrieval, generation) for SERVICE_ROLE.

    `services` (a callable returning the Services to use) lets an internal service run beside a gateway in one
    process, as the tests do; a deployed service uses its own process container.
    """
    settings = get_settings()
    role = role or settings.service_role
    internal = role in ROLE_ROUTERS
    configure_logging(settings.log_level)
    title = settings.app_name if not internal else f"Support IQ {role} service"
    app = FastAPI(title=title, version=settings.app_version, lifespan=make_lifespan(role),
                  docs_url=f"{API_PREFIX}/docs" if not internal else None,
                  openapi_url=f"{API_PREFIX}/openapi.json" if not internal else None)

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

    app.add_middleware(BodySizeLimitMiddleware,
                       max_bytes=INTERNAL_MAX_REQUEST_BYTES if internal else settings.max_request_bytes)
    if not internal:  # internal services are never called from a browser
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT"],
                           allow_headers=["Content-Type", "X-Request-ID", "Authorization"],
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

    if internal:
        provider = {"services": services} if services else {}
        app.include_router(health_router(role, **provider))
        app.include_router(ROLE_ROUTERS[role](**provider))
        return app

    for module in (health, auth, resolve, feedback, knowledge, conversations, emerging_issues, intents, analytics, system):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.get("/")
    def root() -> dict:
        return {"app": settings.app_name, "docs": f"{API_PREFIX}/docs", "health": f"{API_PREFIX}/health"}

    return app


app = create_app()
