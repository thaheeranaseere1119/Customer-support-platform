"""Test fixtures: an isolated SQLite database seeded from the DEMO dataset (data/tickets.csv)."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="telecom-tests-"))
# Approved live queries are appended to the dataset file, so tests work on a copy.
shutil.copy(ROOT / "data" / "tickets.csv", _TMP / "tickets.csv")
os.environ.update({
    "APP_ENV": "test",
    "DEMO_MODE": "true",
    "GEMINI_API_KEY": "",
    "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
    "SQLITE_FALLBACK_URL": f"sqlite:///{_TMP / 'fallback.db'}",
    "DATASET_PATH": str(_TMP / "tickets.csv"),
    "AUTO_SEED": "true",
    "LOG_LEVEL": "WARNING",
    # Test-only staff account and signing key (never used outside this temporary test database).
    "AUTH_ENABLED": "true",
    "AUTH_SECRET_KEY": "test-signing-key-" + uuid.uuid4().hex,
    "ADMIN_USERNAME": "qa-lead",
    "ADMIN_PASSWORD": "test-" + uuid.uuid4().hex,
    "ADMIN_DISPLAY_NAME": "QA Lead",
})
STAFF_CREDENTIALS = {"username": os.environ["ADMIN_USERNAME"], "password": os.environ["ADMIN_PASSWORD"]}
ANONYMOUS = {"Authorization": ""}  # per-request header override: call an endpoint as a customer


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        # Most tests exercise agent features, so the shared client is signed in as staff.
        login = test_client.post("/api/v1/auth/login", json=STAFF_CREDENTIALS)
        assert login.status_code == 200, login.text
        test_client.headers["Authorization"] = f"Bearer {login.json()['token']}"
        yield test_client


@pytest.fixture()
def db(client):
    from app.database import get_sessionmaker

    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def services(client):
    from app.dependencies import get_container

    return get_container().services


@pytest.fixture()
def session_id() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"


def resolve(client, session_id: str, complaint: str, **extra) -> dict:
    response = client.post("/api/v1/resolve", json={"session_id": session_id, "complaint": complaint, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def feedback(client, case_id: str, outcome: str, **extra) -> dict:
    response = client.post("/api/v1/feedback", json={"case_id": case_id, "outcome": outcome, **extra})
    assert response.status_code == 200, response.text
    return response.json()
