"""Integration tests for the adaptive workflow, knowledge evolution, memory,
emerging issues and intent creation."""
from sqlalchemy import func, select

from app.models import CandidateCase, Feedback, ResolutionAttempt
from tests.conftest import feedback, resolve


def test_known_complaint_retrieval_rag_citations(client, session_id):
    data = resolve(client, session_id, "I was charged twice on my mobile bill this month")
    assert data["analysis"]["intent"] == "billing_dispute"
    assert data["resolution"]["status"] == "known"
    assert data["retrieval"]["evidence_score"] >= 0.70
    cited = {c["source_id"] for c in data["citations"]}
    retrieved = {s["source_id"] for s in data["retrieval"]["sources"]}
    assert cited and cited <= retrieved  # every citation refers to a retrieved source
    for step in data["resolution"]["steps"]:
        assert step["kind"] == "resolution" and step["citations"]
        assert set(step["citations"]) <= cited
    assert [p["name"] for p in data["pipeline"]] == ["understanding", "embedding", "retrieving", "reranking",
                                                     "checking_evidence", "generating", "citing", "complete"]


def test_unknown_candidate_feedback_retry_escalation(client, db, session_id):
    complaint = "My car's built-in connectivity module lost its connection after the latest update"
    first = resolve(client, session_id, complaint)
    case_id = first["case_id"]
    assert first["resolution"]["status"] in ("unknown", "uncertain")
    assert first["resolution"]["is_candidate"] is True
    if first["resolution"]["status"] == "unknown":
        assert first["unknown_issue"]["headline"] == "NEW ISSUE DETECTED"

    # Retry is not allowed before feedback.
    assert client.post("/api/v1/resolve/retry", json={"case_id": case_id}).status_code == 409

    fb = feedback(client, case_id, "not_solved")
    assert fb["next_action"] == "retry"
    second = client.post("/api/v1/resolve/retry", json={"case_id": case_id}).json()
    assert second["attempt"]["attempt_number"] == 2
    first_cited = {c["source_id"] for c in first["citations"]}
    assert first_cited.isdisjoint({s["source_id"] for s in second["retrieval"]["sources"]})

    fb = feedback(client, case_id, "partially_solved", comment="It works sometimes")
    assert fb["next_action"] == "provide_more_info"
    third = client.post("/api/v1/resolve/retry", json={"case_id": case_id,
                                                       "additional_info": "The car shows error 503 on the dashboard"}).json()
    assert third["attempt"]["attempt_number"] == 3

    fb = feedback(client, case_id, "not_solved")
    assert fb["next_action"] == "escalated" and fb["case_status"] == "escalated"
    assert client.post("/api/v1/resolve/retry", json={"case_id": case_id}).status_code == 409

    case = client.get(f"/api/v1/cases/{case_id}").json()
    assert case["status"] == "escalated" and case["escalated"] is True
    assert [a["attempt_number"] for a in case["attempts"]] == [1, 2, 3]  # nothing overwritten
    assert [f["outcome"] for f in case["feedback"]] == ["not_solved", "partially_solved", "not_solved"]
    assert case["attempts"][2]["additional_info"].startswith("The car shows error")
    stored = db.scalars(select(Feedback).where(Feedback.case_id == case_id)).all()
    assert all(f.retrieved_source_ids is not None for f in stored)
    assert len(db.scalars(select(ResolutionAttempt).where(ResolutionAttempt.case_id == case_id)).all()) == 3


def test_duplicate_feedback_rejected(client, session_id):
    data = resolve(client, session_id, "My SIM is not detected")
    feedback(client, data["case_id"], "solved")
    again = client.post("/api/v1/feedback", json={"case_id": data["case_id"], "outcome": "solved"})
    assert again.status_code == 409


DATASET_COMPLAINT = ("My calls keep dropping today. The issue has continued despite basic checks. "
                     "I would like to troubleshoot this.")


def test_known_solved_dataset_query_closes_without_candidate(client, db, session_id):
    data = resolve(client, session_id, DATASET_COMPLAINT)
    assert data["resolution"]["status"] == "known"
    fb = feedback(client, data["case_id"], "solved")
    assert fb["next_action"] == "closed" and fb["candidate_id"] is None
    assert db.scalar(select(CandidateCase).where(CandidateCase.case_id == data["case_id"])) is None


def test_known_solved_new_query_goes_to_review_then_into_dataset(client, db, session_id):
    from app.config import get_settings
    from app.models import KnowledgeArticle, Ticket

    complaint = "My calls keep dropping"
    data = resolve(client, session_id, complaint)
    assert data["resolution"]["status"] == "known"
    fb = feedback(client, data["case_id"], "solved")
    assert fb["next_action"] == "candidate_created"
    candidate = db.get(CandidateCase, fb["candidate_id"])
    assert candidate.origin == "kb_match" and candidate.status == "pending_review"

    articles_before = db.scalar(select(func.count()).select_from(KnowledgeArticle))
    approved = client.post(f"/api/v1/knowledge/{candidate.id}/approve", json={"reviewer": "qa-lead"}).json()
    assert approved["status"] == "approved" and approved["article"] is None  # no duplicate article
    record_id = approved["dataset_record_id"]
    assert record_id.startswith("TELCO-LIVE-")
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(KnowledgeArticle)) == articles_before
    ticket = db.get(Ticket, record_id)
    assert ticket.customer_complaint == complaint and ticket.human_verification_status == "human_verified"

    # The row is in the dataset file with the dataset's own columns, and re-ingestion accepts it.
    from app.utils.validation import read_csv_rows
    columns, rows = read_csv_rows(get_settings().dataset_path)
    row = next(r for r in rows if r["record_id"] == record_id)
    assert row["customer_complaint"] == complaint and row["intent"] == ticket.intent and row["resolution"]
    assert row["source"] == "live_customer_chat" and row["human_verification_status"] == "human_verified"
    from app.ingestion import ingest_tickets
    from app.utils.validation import validate_rows
    from app.services.taxonomy import taxonomy_service
    taxonomy = taxonomy_service.get(db)
    report = validate_rows([row], valid_intents=set(taxonomy.intents), valid_categories=taxonomy.domain_categories,
                           columns=columns)
    assert report.ok, report.summary()
    assert ingest_tickets(db, get_settings().dataset_path)["inserted"] == 0  # already loaded, not duplicated

    # The same query asked again is now part of the dataset: solved without another review.
    again = resolve(client, f"{session_id}-2", complaint)
    assert feedback(client, again["case_id"], "solved")["next_action"] == "closed"


def test_candidate_approval_makes_knowledge_retrievable(client, session_id):
    complaint = "The parental control filter blocks my child's school websites on the home network"
    first = resolve(client, session_id, complaint)
    assert first["resolution"]["status"] != "known"
    fb = feedback(client, first["case_id"], "solved")
    assert fb["next_action"] == "candidate_created"
    candidate_id = fb["candidate_id"]

    pending = client.get("/api/v1/candidates", params={"status": "pending_review"}).json()
    assert candidate_id in {c["id"] for c in pending["items"]}
    # Customer YES alone never creates trusted knowledge.
    assert not client.get("/api/v1/knowledge", params={"q": "parental control"}).json()["items"]

    content = ("Symptoms: Parental control filter blocks school websites.\nResolution steps:\n"
               "1. Open the parental control settings in the self-care account.\n"
               "2. Add the school website to the allowed list.\n3. Ask the customer to reload the website.\n"
               "Escalate when: The website is still blocked after it is allowed.\nCaution: Verified by support lead.")
    approved = client.post(f"/api/v1/knowledge/{candidate_id}/approve",
                           json={"reviewer": "qa-lead", "notes": "verified", "content": content,
                                 "title": "Parental control blocks school websites"}).json()
    assert approved["status"] == "approved" and approved["indexed"] is True
    # No issue type was chosen (still "unknown"), so the row cannot be added to the dataset yet.
    assert approved["dataset_record_id"] is None
    article_id = approved["article"]["article_id"]
    assert approved["article"]["status"] == "ACTIVE"

    again = resolve(client, f"{session_id}-b", complaint)
    assert article_id in {s["source_id"] for s in again["retrieval"]["sources"]}
    assert again["resolution"]["status"] == "known"
    assert article_id in {c["source_id"] for c in again["citations"]}

    second = client.post(f"/api/v1/knowledge/{candidate_id}/approve", json={"reviewer": "qa-lead"})
    assert second.status_code == 409


def test_candidate_rejection_stays_out_of_trusted_kb(client, session_id):
    complaint = "My conference bridge dial-in number always gives a busy tone"
    first = resolve(client, session_id, complaint)
    fb = feedback(client, first["case_id"], "solved")
    rejected = client.post(f"/api/v1/knowledge/{fb['candidate_id']}/reject",
                           json={"reviewer": "qa-lead", "notes": "not reproducible"}).json()
    assert rejected["status"] == "rejected" and rejected["article"] is None
    again = resolve(client, f"{session_id}-b", complaint)
    assert all(s["source_type"] != "knowledge_base" or "conference" not in s["title"].lower()
               for s in again["retrieval"]["sources"])


def test_draft_article_approval_and_versioning(client):
    draft = client.get("/api/v1/knowledge/KB-042").json()
    assert draft["status"] == "DRAFT" and draft["indexed_chunks"] == 0
    approved = client.post("/api/v1/knowledge/KB-042/approve", json={"reviewer": "qa-lead"}).json()
    assert approved["article"]["status"] == "ACTIVE"
    assert client.get("/api/v1/knowledge/KB-042").json()["indexed_chunks"] >= 1

    updated = client.put("/api/v1/knowledge/KB-042", json={"title": "Moving an eSIM to a new phone",
                                                           "change_note": "title clarified"}).json()
    assert updated["version"] == 2 and updated["status"] == "ACTIVE"
    detail = client.get("/api/v1/knowledge/KB-042").json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    assert detail["versions"][1]["status"] == "ARCHIVED"


def test_create_knowledge_article_validation(client):
    bad = client.post("/api/v1/knowledge", json={"title": "x", "content": "short", "category": "Nope", "intent": "nope"})
    assert bad.status_code == 422
    ok = client.post("/api/v1/knowledge", json={
        "title": "Wi-Fi channel congestion", "content": "Symptoms: Slow Wi-Fi in apartments.\nResolution steps:\n1. Restart the router.",
        "category": "Wi-Fi", "intent": "wifi_not_working", "status": "DRAFT"})
    assert ok.status_code == 201 and ok.json()["status"] == "DRAFT"


def test_conversation_memory_resolves_follow_up(client, session_id):
    first = client.post(f"/api/v1/conversations/{session_id}/message", json={"message": "My broadband is slow."}).json()
    assert first["resolution"]["analysis"]["intent"] == "broadband_slow"
    assert first["assistant_message"]
    follow = client.post(f"/api/v1/conversations/{session_id}/message", json={"message": "Mostly at night."}).json()
    analysis = follow["resolution"]["analysis"]
    assert analysis["intent"] == "broadband_slow"
    assert analysis["classification_method"] == "memory_carryover"
    assert analysis["used_memory"] is True
    conv = client.get(f"/api/v1/conversations/{session_id}").json()
    assert [m["role"] for m in conv["messages"]].count("user") == 2
    assert conv["memory"]["intent"] == "broadband_slow"
    assert any(e["value"].lower().endswith("night") for e in conv["memory"]["entities"])
    assert "broadband" in conv["memory_summary"].lower()


def test_new_unrelated_complaint_is_not_hijacked_by_memory(client, session_id):
    first = resolve(client, session_id, "My broadband drops every evening around 8 PM")
    assert first["analysis"]["intent"] == "broadband_disconnects"
    unrelated = resolve(client, session_id, "Visual voicemail transcription stopped working after the carrier settings update")
    assert unrelated["analysis"]["intent"] == "unknown"
    assert unrelated["analysis"]["classification_method"] != "memory_carryover"
    state = unrelated["memory"]["state"]
    assert state["issue"].startswith("Visual voicemail") and state["intent"] == "unknown"
    assert not any(e["value"] == "8 PM" for e in state["entities"])  # old issue details not mixed in
    assert len(state["previous_resolutions"]) == 2  # history is kept


def test_memory_context_is_bounded(client, session_id):
    for i in range(14):
        client.post(f"/api/v1/conversations/{session_id}/message", json={"message": f"My wifi is not working, try {i}"})
    data = resolve(client, session_id, "still the same")
    assert data["memory"]["turns"] <= 10


def test_emerging_issue_detection_and_new_intent(client, session_id):
    complaints = [
        "Visual voicemail transcription stopped working after the carrier settings update",
        "My visual voicemail no longer shows transcriptions of messages",
        "Voicemail transcription text is missing in the visual voicemail app",
    ]
    for i, text in enumerate(complaints):
        data = resolve(client, f"{session_id}-{i}", text)
        assert data["resolution"]["status"] == "unknown"
    issues = client.get("/api/v1/emerging-issues").json()
    issue = next(i for i in issues if "voicemail" in " ".join(i["keywords"]).lower())
    assert issue["status"] == "NEW" and issue["occurrences"] >= 3
    detail = client.get(f"/api/v1/emerging-issues/{issue['id']}").json()
    assert len(detail["members"]) >= 3

    review = client.post(f"/api/v1/emerging-issues/{issue['id']}/status", json={"status": "UNDER_REVIEW"}).json()
    assert review["status"] == "UNDER_REVIEW"

    created = client.post(f"/api/v1/emerging-issues/{issue['id']}/create-intent", json={
        "name": "visual_voicemail_transcription", "display_name": "Visual Voicemail Transcription",
        "description": "Visual voicemail transcriptions are missing", "parent_category": "Calls",
        "example_complaints": complaints, "keywords": ["voicemail transcription", "visual voicemail"],
        "resolution_title": "Visual voicemail transcription missing",
        "resolution_steps": ["Confirm visual voicemail is enabled on the line.",
                             "Restart the device to reload voicemail settings.",
                             "Record the device model and escalate if transcriptions remain missing."]}).json()
    assert created["intent"]["name"] == "visual_voicemail_transcription"
    assert created["article"]["status"] == "ACTIVE"
    assert client.get(f"/api/v1/emerging-issues/{issue['id']}").json()["status"] == "APPROVED"
    intents = {i["name"] for i in client.get("/api/v1/intents").json()["intents"]}
    assert "visual_voicemail_transcription" in intents

    after = resolve(client, f"{session_id}-after", "Visual voicemail transcription is not showing for new messages")
    assert after["analysis"]["intent"] == "visual_voicemail_transcription"
    assert after["resolution"]["status"] == "known"
    assert created["article"]["article_id"] in {c["source_id"] for c in after["citations"]}


def test_create_intent_validation(client):
    bad = client.post("/api/v1/intents", json={"name": "Bad Name!", "description": "desc here", "parent_category": "Calls",
                                               "example_complaints": ["x"]})
    assert bad.status_code == 422
    dup = client.post("/api/v1/intents", json={"name": "call_drops", "description": "duplicate", "parent_category": "Calls",
                                               "example_complaints": ["calls drop"]})
    assert dup.status_code == 409
    ok = client.post("/api/v1/intents", json={"name": "hotspot_blocked", "description": "Hotspot tethering blocked",
                                              "parent_category": "Mobile",
                                              "example_complaints": ["Hotspot tethering is blocked on my plan"],
                                              "keywords": ["hotspot", "tethering"]})
    assert ok.status_code == 201
    assert ok.json()["intent"]["support_category"] == "Mobile"


def test_analytics_and_logs(client):
    data = client.get("/api/v1/analytics").json()
    stats = data["stats"]
    for key in ("total_tickets", "resolved_cases", "unknown_issues", "knowledge_articles", "resolution_success_rate"):
        assert key in stats
    assert stats["live_cases"] > 0 and len(data["activity"]) == 14
    logs = client.get("/api/v1/logs", params={"event": "resolution_completed"}).json()["items"]
    assert logs and "evidence_score" in logs[0]["payload"]
    assert "api_key" not in str(logs).lower()


def test_mobile_data_not_working_is_answered_from_its_kb_article(client, session_id):
    data = resolve(client, session_id, "My mobile data is not working")
    assert data["analysis"]["intent"] == "mobile_data_not_working"
    assert data["resolution"]["status"] == "known"
    assert "KB-001" in {c["source_id"] for c in data["citations"]}
    assert all(step["citations"] for step in data["resolution"]["steps"])


def test_unseen_issue_gets_cited_general_guidance_but_stays_unknown(client, session_id):
    data = resolve(client, session_id, "My car's built-in connectivity module lost its connection after the update")
    assert data["resolution"]["status"] == "unknown"
    assert data["unknown_issue"]["headline"] == "NEW ISSUE DETECTED"
    assert data["resolution"]["is_candidate"] is True
    assert data["resolution"]["summary"].startswith("BEST-SUITABLE GUIDANCE")
    cited = {c["source_id"] for c in data["citations"]}
    assert cited and all(c.startswith("KB-") for c in cited)
    assert all(step["citations"] for step in data["resolution"]["steps"])


def test_conversation_reply_contains_cited_steps_and_feedback_question(client, session_id):
    reply = client.post(f"/api/v1/conversations/{session_id}/message", json={"message": "My bill payment failed"}).json()
    text = reply["assistant_message"]
    assert "1. " in text and "[KB-021]" in text
    assert text.strip().endswith("Did this solve the problem?")


def test_candidates_for_published_knowledge_are_approved_not_pending(client):
    approved = client.get("/api/v1/candidates", params={"status": "approved", "origin": "dataset"}).json()
    linked = {c["intent"]: c["approved_article_id"] for c in approved["items"]}
    assert linked.get("mobile_data_not_working") == "KB-001"
    assert linked.get("payment_failed") == "KB-021"
    assert linked.get("broadband_no_internet") == "KB-011"
    pending = client.get("/api/v1/candidates", params={"status": "pending_review", "origin": "dataset"}).json()
    assert pending["total"] == 0
    assert set(approved["origin_counts"]) >= {"dataset", "demo_seed"}
    # Resolved patterns no longer surface as open emerging issues.
    open_issues = [i for i in client.get("/api/v1/emerging-issues").json() if i["status"] in ("NEW", "UNDER_REVIEW")]
    assert all("mobile_data" not in i["suggested_intent_name"] for i in open_issues)
