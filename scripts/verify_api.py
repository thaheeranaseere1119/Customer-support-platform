"""Live smoke test of every API endpoint against a running backend.

Usage: python scripts/verify_api.py [--base http://127.0.0.1:8000] [--username NAME]

Agent endpoints need a staff login: the password is read from STAFF_PASSWORD (or ADMIN_PASSWORD, e.g. from .env),
never from the command line. The username defaults to STAFF_USERNAME / ADMIN_USERNAME.

It exercises the full workflow (resolve -> feedback -> retry -> candidate -> approve,
draft reject, intents, emerging issues, conversations, analytics) and prints a
pass/fail table. It writes demo data, so run `python scripts/ingest_data.py --reset`
afterwards if you want a clean database.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

RESULTS: list[tuple[str, str, int, bool, str]] = []
HEADERS = {"Content-Type": "application/json"}


def call(base: str, method: str, path: str, body: dict | None = None, expect: int = 200, label: str | None = None,
         anonymous: bool = False):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if anonymous else HEADERS
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            status, payload = resp.status, resp.read()
    except urllib.error.HTTPError as err:
        status, payload = err.code, err.read()
    try:
        parsed = json.loads(payload) if payload and not path.endswith("/stream") else payload
    except json.JSONDecodeError:
        parsed = payload
    ok = status == expect
    note = ""
    if isinstance(parsed, dict) and "error" in parsed:
        note = parsed["error"].get("code", "")
    RESULTS.append((method, label or path, status, ok, note))
    return parsed


def main(base: str, username: str | None, password: str | None) -> int:
    api = base.rstrip("/") + "/api/v1"
    sid = f"verify-{uuid.uuid4().hex[:8]}"
    call(api, "GET", "/health")
    call(api, "GET", "/cases", expect=401, label="/cases (no login -> 401)", anonymous=True)
    if username and password:
        login = call(api, "POST", "/auth/login", {"username": username, "password": password}, label="/auth/login")
        if isinstance(login, dict) and login.get("token"):
            HEADERS["Authorization"] = f"Bearer {login['token']}"
        call(api, "GET", "/auth/me")
    else:
        print("No staff credentials (set STAFF_USERNAME / STAFF_PASSWORD); agent endpoints will fail.\n")
    known = call(api, "POST", "/resolve", {"session_id": sid, "complaint": "My broadband keeps disconnecting every evening around 8 PM"})
    call(api, "POST", "/resolve", {"session_id": sid, "complaint": ""}, expect=422, label="/resolve (empty complaint -> 422)")
    call(api, "POST", "/resolve/stream", {"session_id": sid, "complaint": "My calls keep dropping"}, label="/resolve/stream")
    call(api, "GET", f"/cases/{known['case_id']}", label="/cases/{case_id}")
    call(api, "GET", "/cases")

    unknown = call(api, "POST", "/resolve", {"session_id": f"{sid}-u", "complaint": "My e-reader cannot download books over the cellular connection"},
                   label="/resolve (unknown issue)")
    case_id = unknown["case_id"]
    call(api, "POST", "/feedback", {"case_id": case_id, "outcome": "not_solved"}, label="/feedback (NO)")
    call(api, "POST", "/resolve/retry", {"case_id": case_id}, label="/resolve/retry")
    fb = call(api, "POST", "/feedback", {"case_id": case_id, "outcome": "solved"}, label="/feedback (YES -> candidate)")
    candidate = fb.get("candidate_id")

    call(api, "GET", "/knowledge")
    call(api, "GET", "/knowledge/KB-010", label="/knowledge/{id}")
    created = call(api, "POST", "/knowledge", {"title": "Verify API draft article", "content": "Symptoms: test.\nResolution steps:\n1. Restart the device.",
                                                "category": "Mobile", "intent": "mobile_data_slow", "status": "DRAFT"}, expect=201)
    art = created["article_id"]
    call(api, "PUT", f"/knowledge/{art}", {"title": "Verify API draft article v2"}, label="/knowledge/{id} (PUT -> new version)")
    call(api, "POST", f"/knowledge/{art}/reject", {"reviewer": "verify"}, label="/knowledge/{id}/reject")
    if candidate:
        call(api, "POST", f"/knowledge/{candidate}/approve", {"reviewer": "verify", "content": "Symptoms: e-reader cannot download.\nResolution steps:\n1. Confirm the e-reader has cellular service enabled.\n2. Restart the e-reader and retry the download."},
             label="/knowledge/{candidate}/approve")
    call(api, "GET", "/candidates")

    for i, text in enumerate(["My e-SIM QR code says it was already used on my tablet",
                              "Tablet eSIM QR code shows already used error",
                              "The eSIM QR code for my tablet is rejected as already used"]):
        call(api, "POST", "/resolve", {"session_id": f"{sid}-e{i}", "complaint": text}, label=f"/resolve (cluster seed {i + 1})")
    call(api, "POST", "/emerging-issues/detect", {})
    issues = call(api, "GET", "/emerging-issues")
    open_issue = next((i for i in issues if i["status"] in ("NEW", "UNDER_REVIEW")), None)
    if open_issue:
        call(api, "GET", f"/emerging-issues/{open_issue['id']}", label="/emerging-issues/{id}")
        name = f"verify_intent_{uuid.uuid4().hex[:6]}"
        call(api, "POST", f"/emerging-issues/{open_issue['id']}/create-intent",
             {"name": name, "description": "Created by verify_api", "parent_category": "SIM",
              "example_complaints": open_issue["example_complaints"][:3] or ["example"],
              "resolution_steps": ["Record the device model and escalate."]}, label="/emerging-issues/{id}/create-intent")
    call(api, "GET", "/intents")
    call(api, "POST", "/intents", {"name": f"verify_manual_{uuid.uuid4().hex[:6]}", "description": "Manual intent from verify_api",
                                   "parent_category": "Mobile", "example_complaints": ["hotspot is blocked on my plan"]}, expect=201)
    call(api, "GET", f"/conversations/{sid}", label="/conversations/{session_id}")
    call(api, "POST", f"/conversations/{sid}/message", {"message": "It still happens at night"}, label="/conversations/{session_id}/message")
    chat = call(api, "POST", "/conversations", {"customer_name": "Verify"}, expect=201, label="/conversations (start customer chat)")
    cid = chat["session_id"]
    call(api, "POST", f"/conversations/{cid}/message", {"message": "My SIM is not detected"}, label="/conversations/{id}/message (bot)")
    call(api, "POST", f"/conversations/{cid}/handoff", {"action": "request"}, label="/conversations/{id}/handoff request")
    call(api, "GET", "/conversations?handoff_status=needs_agent", label="/conversations (admin inbox)")
    call(api, "POST", f"/conversations/{cid}/handoff", {"action": "take", "agent": "Verifier"}, label="/conversations/{id}/handoff take")
    routed = call(api, "POST", f"/conversations/{cid}/message", {"message": "Hello?"}, label="/conversations/{id}/message (to agent)")
    if routed.get("handled_by") != "agent":
        RESULTS.append(("POST", "customer message routed to agent", 0, False, "handled_by mismatch"))
    call(api, "POST", f"/conversations/{cid}/agent-message", {"agent": "Verifier", "message": "Hi, how can I help?"}, label="/conversations/{id}/agent-message")
    call(api, "POST", f"/conversations/{cid}/read", {}, label="/conversations/{id}/read")
    call(api, "POST", f"/conversations/{cid}/handoff", {"action": "close", "agent": "Verifier"}, label="/conversations/{id}/handoff close")
    call(api, "GET", "/analytics")
    call(api, "GET", "/settings")
    call(api, "GET", "/logs")

    width = max(len(r[1]) for r in RESULTS)
    failures = 0
    for method, path, status, ok, note in RESULTS:
        failures += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {method:5} {path:<{width}}  {status} {note}")
    print(f"\n{len(RESULTS) - failures}/{len(RESULTS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default=os.environ.get("STAFF_USERNAME") or os.environ.get("ADMIN_USERNAME"))
    args = parser.parse_args()
    started = time.time()
    username, password = args.username, os.environ.get("STAFF_PASSWORD") or os.environ.get("ADMIN_PASSWORD")
    if not (username and password):  # fall back to the first staff account configured in .env
        try:
            import _bootstrap  # noqa: F401

            from app.config import get_settings
            settings = get_settings()
            username = username or settings.admin_username
            password = password or (settings.admin_password.get_secret_value() if settings.admin_password else None)
        except Exception:  # backend not importable here: stay anonymous
            pass
    code = main(args.base, username, password)
    print(f"({time.time() - started:.1f}s)")
    sys.exit(code)
