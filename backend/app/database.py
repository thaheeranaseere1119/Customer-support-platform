"""Database engine management.

PostgreSQL (+ pgvector when installed) is the production target. If the primary
database cannot be reached and DB_FALLBACK_TO_SQLITE=true, the app degrades to a
local SQLite file and an in-memory vector index instead of crashing.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sqlalchemy import LargeBinary, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

logger = logging.getLogger(__name__)

try:  # optional dependency
    from pgvector.sqlalchemy import Vector as PgVector
except Exception:  # pragma: no cover - depends on environment
    PgVector = None


@dataclass
class DatabaseState:
    url_backend: str = "unknown"
    using_fallback: bool = False
    pgvector: bool = False
    available: bool = False
    error: str | None = None
    connected_at: float | None = None
    extra: dict = field(default_factory=dict)


db_state = DatabaseState()
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None
_lock = threading.Lock()


class Base(DeclarativeBase):
    pass


class EmbeddingType(TypeDecorator):
    """Stores embeddings as pgvector `vector(dim)` on PostgreSQL+pgvector,
    otherwise as raw float32 bytes. Always returns a numpy array."""

    impl = LargeBinary
    cache_ok = True

    def __init__(self, dim: int = 384, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and db_state.pgvector and PgVector is not None:
            return dialect.type_descriptor(PgVector(self.dim))
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        arr = np.asarray(value, dtype=np.float32)
        if dialect.name == "postgresql" and db_state.pgvector and PgVector is not None:
            return arr.tolist()
        return arr.tobytes()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray, memoryview)):
            return np.frombuffer(bytes(value), dtype=np.float32).copy()
        return np.asarray(value, dtype=np.float32)


def _build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        path = url.replace("sqlite:///", "", 1)
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        return engine
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)


def _probe(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def _enable_pgvector(engine: Engine) -> bool:
    settings = get_settings()
    if not settings.pgvector_enabled or PgVector is None:
        return False
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            found = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first()
        return found is not None
    except Exception as exc:  # extension not installed on server
        logger.warning("pgvector unavailable, using in-memory vector index: %s", exc.__class__.__name__)
        return False


def init_engine(database_url: str | None = None, force: bool = False) -> Engine:
    """Create (or return) the global engine, falling back to SQLite if needed."""
    global _engine, _SessionLocal
    with _lock:
        if _engine is not None and not force:
            return _engine
        settings = get_settings()
        url = database_url or settings.database_url
        backend = "postgresql" if url.startswith("postgres") else "sqlite"
        engine: Engine | None = None
        last_error: Exception | None = None
        retries = settings.db_connect_retries if backend == "postgresql" else 1
        for attempt in range(1, retries + 1):
            try:
                candidate = _build_engine(url)
                _probe(candidate)
                engine = candidate
                break
            except Exception as exc:
                last_error = exc
                logger.warning("Database connection attempt %s/%s failed (%s)", attempt, retries, exc.__class__.__name__)
                if attempt < retries:
                    time.sleep(settings.db_connect_retry_seconds)

        db_state.using_fallback = False
        db_state.error = None
        if engine is None:
            if settings.db_fallback_to_sqlite and backend != "sqlite":
                logger.error("Primary database unavailable; falling back to SQLite at %s", settings.sqlite_fallback_url)
                engine = _build_engine(settings.sqlite_fallback_url)
                _probe(engine)
                backend = "sqlite"
                db_state.using_fallback = True
                db_state.error = f"Primary database unreachable ({last_error.__class__.__name__}); using SQLite fallback"
            else:
                db_state.available = False
                db_state.error = f"Database unavailable ({last_error.__class__.__name__ if last_error else 'unknown'})"
                raise RuntimeError(db_state.error)

        db_state.url_backend = backend
        db_state.pgvector = _enable_pgvector(engine) if backend == "postgresql" else False
        db_state.available = True
        db_state.connected_at = time.time()
        _engine = engine
        _SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        return engine


def get_engine() -> Engine:
    return _engine if _engine is not None else init_engine()


def get_sessionmaker() -> sessionmaker:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def create_all() -> None:
    from app import models  # noqa: F401  (register models)

    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Dispose the engine (used by tests and the migration script)."""
    global _engine, _SessionLocal
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _SessionLocal = None
