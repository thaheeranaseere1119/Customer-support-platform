"""Health endpoint, structured errors, request IDs, validation and size limits."""
from tests.conftest import resolve


def test_health_reports_components(client):
    data = client.get("/api/v1/health").json()
    assert data["status"] in ("ok", "degraded")
    assert data["mode"] == "DEMO MODE"
    assert data["demo_mode"] is True
    assert data["llm_provider"] == "mock"
    assert data["database"]["available"] is True
    assert data["counts"]["tickets"] > 100
    assert data["counts"]["active_articles"] >= 30
    assert data["index"]["documents"] > 0


def test_request_id_header_and_security_headers(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_unknown_route_returns_structured_error(client):
    body = client.get("/api/v1/does-not-exist").json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"]


def test_empty_complaint_rejected(client, session_id):
    response = client.post("/api/v1/resolve", json={"session_id": session_id, "complaint": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_extra_fields_and_bad_session_rejected(client):
    bad = client.post("/api/v1/resolve", json={"session_id": "bad id with spaces", "complaint": "no signal"})
    assert bad.status_code == 422
    extra = client.post("/api/v1/resolve", json={"session_id": "ok-1", "complaint": "no signal", "admin": True})
    assert extra.status_code == 422


def test_overlong_complaint_rejected(client, session_id):
    response = client.post("/api/v1/resolve", json={"session_id": session_id, "complaint": "a" * 2001})
    assert response.status_code == 422


def test_request_size_limit(client):
    response = client.post("/api/v1/resolve", content=b"{" + b" " * 70_000 + b"}",
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_case_not_found(client):
    response = client.get("/api/v1/cases/CASE-NOPE")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_html_in_complaint_is_returned_as_plain_text(client, session_id):
    data = resolve(client, session_id, "<script>alert(1)</script> my wifi is not working")
    assert data["analysis"]["intent"] == "wifi_not_working"
    case = client.get(f"/api/v1/cases/{data['case_id']}").json()
    assert case["complaint"].startswith("<script>")  # stored verbatim, rendered as text by the UI


def test_settings_read_and_update(client):
    data = client.get("/api/v1/settings").json()
    assert data["tunable"]["known_threshold"] == 0.70
    assert "gemini_api_key" not in str(data).lower()
    bad = client.put("/api/v1/settings", json={"known_threshold": 0.3, "unknown_threshold": 0.5})
    assert bad.status_code == 422
    ok = client.put("/api/v1/settings", json={"top_k": 12})
    assert ok.status_code == 200 and ok.json()["tunable"]["top_k"] == 12
    client.put("/api/v1/settings", json={"top_k": 10})
