"""Staff sign-in, and the split between public customer endpoints and staff-only agent endpoints."""
import pytest

from app.services import auth
from tests.conftest import ANONYMOUS, STAFF_CREDENTIALS

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clear_lockouts():
    auth.reset_login_failures()
    yield
    auth.reset_login_failures()


def test_password_hashes_are_salted_and_verifiable():
    first, second = auth.hash_password("correct horse battery"), auth.hash_password("correct horse battery")
    assert first != second and first.startswith("pbkdf2_sha256$")
    assert auth.verify_password("correct horse battery", first)
    assert not auth.verify_password("wrong password!", first)
    assert not auth.verify_password("anything", "not-a-hash")


def test_login_returns_a_token_for_the_staff_member(client):
    response = client.post(f"{API}/auth/login", json=STAFF_CREDENTIALS, headers=ANONYMOUS)
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"username": "qa-lead", "display_name": "QA Lead"} and body["token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.json()["user"]["username"] == "qa-lead"


def test_wrong_password_is_rejected_then_locked_out(client):
    bad = {"username": STAFF_CREDENTIALS["username"], "password": "not-the-password"}
    for _ in range(5):
        response = client.post(f"{API}/auth/login", json=bad, headers=ANONYMOUS)
        assert response.status_code == 401 and response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    locked = client.post(f"{API}/auth/login", json=STAFF_CREDENTIALS, headers=ANONYMOUS)
    assert locked.status_code == 429  # even the right password waits out the lockout


def test_unknown_user_gets_the_same_error_as_a_wrong_password(client):
    response = client.post(f"{API}/auth/login", json={"username": "nobody", "password": "whatever-123"}, headers=ANONYMOUS)
    assert response.status_code == 401 and response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_tampered_and_expired_tokens_are_rejected(client, monkeypatch):
    token = client.post(f"{API}/auth/login", json=STAFF_CREDENTIALS, headers=ANONYMOUS).json()["token"]
    _, signature = token.split(".")
    forged = auth._b64(b'{"sub":"qa-lead","exp":9999999999}') + "." + signature
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    monkeypatch.setattr(auth.time, "time", lambda: 10**10)  # far in the future: the token has expired
    expired = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "SESSION_EXPIRED"


STAFF_ONLY = [
    ("get", "/conversations"), ("get", "/cases"), ("get", "/candidates"), ("get", "/emerging-issues"),
    ("post", "/emerging-issues/detect"), ("get", "/analytics"), ("get", "/analytics/evaluations"),
    ("get", "/settings"), ("put", "/settings"), ("get", "/logs"), ("post", "/resolve"), ("post", "/resolve/stream"),
    ("post", "/knowledge"), ("put", "/knowledge/KB-010"), ("post", "/knowledge/KB-042/approve"),
    ("post", "/knowledge/KB-042/reject"), ("post", "/intents"),
]


@pytest.mark.parametrize(("method", "path"), STAFF_ONLY)
def test_agent_endpoints_need_a_staff_login(client, method, path):
    response = getattr(client, method)(f"{API}{path}", headers=ANONYMOUS,
                                       **({"json": {}} if method in ("post", "put") else {}))
    assert response.status_code == 401 and response.json()["error"]["code"] == "UNAUTHORIZED"


def test_customer_chat_works_without_a_login(client):
    chat = client.post(f"{API}/conversations", json={"customer_name": "Asha"}, headers=ANONYMOUS).json()
    sid = chat["session_id"]
    reply = client.post(f"{API}/conversations/{sid}/message", json={"message": "My broadband is slow"},
                        headers=ANONYMOUS).json()
    case_id = reply["resolution"]["case_id"]
    assert client.get(f"{API}/conversations/{sid}", headers=ANONYMOUS).status_code == 200
    assert client.get(f"{API}/cases/{case_id}", headers=ANONYMOUS).status_code == 200
    assert client.post(f"{API}/feedback", json={"case_id": case_id, "outcome": "not_solved"},
                       headers=ANONYMOUS).json()["next_action"] == "retry"
    assert client.post(f"{API}/resolve/retry", json={"case_id": case_id}, headers=ANONYMOUS).status_code == 200
    for action in ("request", "cancel"):
        assert client.post(f"{API}/conversations/{sid}/handoff", json={"action": action},
                           headers=ANONYMOUS).status_code == 200


def test_customers_cannot_act_as_agents(client):
    sid = client.post(f"{API}/conversations", json={"customer_name": "Asha"}, headers=ANONYMOUS).json()["session_id"]
    for action in ("take", "release", "close"):
        response = client.post(f"{API}/conversations/{sid}/handoff", json={"action": action}, headers=ANONYMOUS)
        assert response.status_code == 401
    assert client.post(f"{API}/conversations/{sid}/agent-message", json={"message": "hi"},
                       headers=ANONYMOUS).status_code == 401
    assert client.post(f"{API}/conversations/{sid}/handoff", json={"action": "take", "agent": "QA Lead"}).status_code == 200


def test_help_center_sees_only_published_articles(client):
    public = client.get(f"{API}/knowledge", params={"status": "DRAFT", "page_size": 100}, headers=ANONYMOUS).json()
    assert public["items"] and all(a["status"] == "ACTIVE" for a in public["items"])
    staff = client.get(f"{API}/knowledge", params={"status": "DRAFT", "page_size": 100}).json()
    assert staff["items"] and all(a["status"] == "DRAFT" for a in staff["items"])
    draft_id = staff["items"][0]["article_id"]
    assert client.get(f"{API}/knowledge/{draft_id}", headers=ANONYMOUS).status_code == 404
    assert client.get(f"{API}/knowledge/{draft_id}").status_code == 200
    assert client.get(f"{API}/knowledge/KB-010", headers=ANONYMOUS).status_code == 200
    assert client.get(f"{API}/intents", headers=ANONYMOUS).status_code == 200  # help-center topics
    assert client.get(f"{API}/health", headers=ANONYMOUS).status_code == 200
