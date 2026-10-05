"""Check that a running backend drafts resolutions with the LLM (AI mode) and that they stay grounded.

Usage: python scripts/verify_llm.py [--base http://127.0.0.1:8000]

Set DEMO_MODE=false and GEMINI_API_KEY in .env and restart the backend first. Signs in with the staff account
from .env (ADMIN_USERNAME / ADMIN_PASSWORD) or STAFF_USERNAME / STAFF_PASSWORD. For each sample complaint it
reports which generator answered, whether every step cites a retrieved source, and what the grounding guard
removed. Exit code 0 only when every answer came from the LLM and every step is cited.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

import _bootstrap  # noqa: F401

SAMPLES = [
    ("My broadband drops every evening around 8 and I've already restarted the router twice, "
     "I work from home and this is costing me"),
    "I was charged twice for my mobile bill this month",
    "My SIM is not detected after I dropped my phone",
    "Mobile data stopped working when I landed in Spain even though roaming is on",
    "My smartwatch eSIM stopped sharing my phone number",  # likely uncertain/unknown: should be a labelled candidate
]


def request(base: str, method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body else None, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def credentials() -> tuple[str | None, str | None]:
    username, password = os.environ.get("STAFF_USERNAME"), os.environ.get("STAFF_PASSWORD")
    if not (username and password):
        from app.config import get_settings
        settings = get_settings()
        username = username or settings.admin_username
        password = password or (settings.admin_password.get_secret_value() if settings.admin_password else None)
    return username, password


def main(base: str) -> int:
    api = base.rstrip("/") + "/api/v1"
    _, health = request(api, "GET", "/health")
    print(f"Mode: {health.get('mode')} | LLM provider: {health.get('llm_provider')} | "
          f"Gemini key configured: {health.get('gemini_configured')}")
    if health.get("mode") != "AI MODE":
        print("\nThe backend is in DEMO MODE: set DEMO_MODE=false and GEMINI_API_KEY in .env, then restart it.")
        return 1
    username, password = credentials()
    status, login = request(api, "POST", "/auth/login", {"username": username, "password": password})
    if status != 200:
        print(f"Staff sign-in failed ({status}): {login.get('error', {}).get('message')}")
        return 1
    token = login["token"]

    failures = 0
    for complaint in SAMPLES:
        status, data = request(api, "POST", "/resolve", {"session_id": f"llm-{uuid.uuid4().hex[:8]}",
                                                         "complaint": complaint}, token)
        if status != 200:
            print(f"\nFAIL  HTTP {status}: {complaint}")
            failures += 1
            continue
        res, sources = data["resolution"], {s["source_id"] for s in data["retrieval"]["sources"]}
        steps = res["steps"]
        cited = bool(steps) and all(s["citations"] and set(s["citations"]) <= sources for s in steps)
        from_llm = res["generator"] == health.get("llm_provider")
        ok = from_llm and cited
        failures += 0 if ok else 1
        guard = res.get("guard_report") or {}
        print(f"\n{'PASS' if ok else 'FAIL'}  {complaint}")
        print(f"      intent={data['analysis']['intent']} evidence={data['retrieval']['evidence']['score']:.2f} "
              f"({res['status']}) generator={res['generator']} label={res.get('label')}")
        print(f"      steps={len(steps)} all cited={cited} | guard removed: {len(guard.get('removed_steps', []))} steps, "
              f"{len(guard.get('removed_citations', []))} citations, {guard.get('removed_figures', 0)} figures")
        for step in steps:
            print(f"        - {step['text']} {step['citations']}")
        for warning in res.get("warnings", []):
            print(f"      ! {warning}")
    print(f"\n{len(SAMPLES) - failures}/{len(SAMPLES)} answers drafted by the LLM with every step cited")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    sys.exit(main(parser.parse_args().base))
