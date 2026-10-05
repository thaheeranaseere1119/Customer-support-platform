"""End-to-end: the reference complaint and an unknown complaint through the public API,
including the streaming endpoint the frontend uses for the live pipeline."""
import json

from tests.conftest import resolve

REFERENCE = "My broadband drops every evening around 8 PM and I already restarted the router twice."


def test_reference_complaint_end_to_end(client, session_id):
    data = resolve(client, session_id, REFERENCE)
    analysis = data["analysis"]
    assert data["request_id"] and data["case_id"].startswith("CASE-")
    assert analysis["intent"] == "broadband_disconnects"
    assert analysis["product"] == "broadband"
    assert analysis["severity"] in ("medium", "high")
    assert analysis["sentiment"] in ("negative", "frustrated", "urgent")
    assert {e["type"] for e in analysis["entities"]} >= {"time", "device", "frequency"}
    assert data["retrieval"]["sources"] and data["retrieval"]["evidence_score"] >= 0.70
    for source in data["retrieval"]["sources"]:
        for key in ("source_id", "source_type", "title", "excerpt", "semantic_score", "keyword_score", "final_score"):
            assert key in source
    assert data["resolution"]["status"] == "known"
    assert data["resolution"]["summary"] and data["resolution"]["steps"]
    assert data["citations"]
    assert any(s["already_attempted"] for s in data["resolution"]["steps"])  # router restart already tried
    assert data["mode"] == "DEMO MODE"


def test_unknown_complaint_end_to_end(client, session_id):
    data = resolve(client, session_id, "The satellite emergency texting feature is greyed out on my phone")
    assert data["resolution"]["status"] in ("unknown", "uncertain")
    assert data["resolution"]["is_candidate"] is True
    assert data["retrieval"]["evidence_score"] < 0.70
    assert data["attempt"]["can_retry"] is True


def test_streaming_pipeline_emits_stages_then_result(client, session_id):
    events = []
    with client.stream("POST", "/api/v1/resolve/stream", json={"session_id": session_id, "complaint": REFERENCE,
                                                               "input_mode": "voice"}) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line:
                events.append(json.loads(line))
    stage_names = [e["name"] for e in events if e["type"] == "stage" and e["status"] != "running"]
    assert stage_names == ["understanding", "embedding", "retrieving", "reranking", "checking_evidence", "generating",
                           "citing", "complete"]
    assert any(e["type"] == "stage" and e["status"] == "running" for e in events)
    result = events[-1]
    assert result["type"] == "result" and result["data"]["analysis"]["intent"] == "broadband_disconnects"


def test_guided_and_free_text_share_the_pipeline(client, session_id):
    guided = resolve(client, session_id, "My SIM is not detected", guided_category="SIM", input_mode="guided")
    free = resolve(client, f"{session_id}-free", "My SIM is not detected")
    assert guided["analysis"]["intent"] == free["analysis"]["intent"] == "sim_not_detected"
    assert [p["name"] for p in guided["pipeline"]] == [p["name"] for p in free["pipeline"]]
