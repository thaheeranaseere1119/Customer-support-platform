"""User portal <-> admin portal workflow: chat, human handoff, agent replies, notifications."""
from tests.conftest import feedback


def start(client, name="Asha"):
    r = client.post("/api/v1/conversations", json={"customer_name": name})
    assert r.status_code == 201, r.text
    return r.json()


def say(client, sid, text):
    r = client.post(f"/api/v1/conversations/{sid}/message", json={"message": text})
    assert r.status_code == 200, r.text
    return r.json()


def handoff(client, sid, action, **extra):
    r = client.post(f"/api/v1/conversations/{sid}/handoff", json={"action": action, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_customer_chat_starts_with_greeting_and_bot_answers_with_citations(client):
    chat = start(client)
    assert chat["channel"] == "customer_app" and chat["handoff_status"] == "bot"
    assert chat["messages"][0]["role"] == "assistant" and "Asha" in chat["messages"][0]["message"]
    reply = say(client, chat["session_id"], "My mobile data is not working")
    assert reply["handled_by"] == "bot"
    assert reply["resolution"]["citations"]
    assert reply["assistant_message"].strip().endswith("Did this solve the problem?")


def test_full_human_handoff_workflow(client):
    sid = start(client, "Ravi")["session_id"]
    say(client, sid, "My SIM is not detected")

    waiting = handoff(client, sid, "request", reason="Wants to talk to a person")
    assert waiting["handoff_status"] == "needs_agent"
    inbox = client.get("/api/v1/conversations").json()
    assert inbox["items"][0]["session_id"] == sid  # needs-agent chats are listed first
    assert inbox["items"][0]["agent_unread"] >= 1

    # While waiting, the bot keeps helping.
    assert say(client, sid, "My calls keep dropping")["handled_by"] == "bot"

    taken = handoff(client, sid, "take", agent="Priya")
    assert taken["handoff_status"] == "agent" and taken["assigned_agent"] == "Priya" and taken["agent_unread"] == 0
    routed = say(client, sid, "Are you there?")
    assert routed["handled_by"] == "agent" and routed["resolution"] is None
    assert routed["conversation"]["agent_unread"] == 1

    after = client.post(f"/api/v1/conversations/{sid}/agent-message", json={"agent": "Priya", "message": "Yes, I'm checking your line now."}).json()
    agent_msgs = [m for m in after["messages"] if m["role"] == "agent"]
    assert agent_msgs and agent_msgs[-1]["message"].startswith("Yes, I'm checking")

    released = handoff(client, sid, "release", agent="Priya")
    assert released["handoff_status"] == "bot"
    assert released["assigned_agent"] is None and released["agent_unread"] == 0
    assert say(client, sid, "My wifi is not working")["handled_by"] == "bot"

    closed = handoff(client, sid, "close", agent="Priya", resolved=True)
    assert closed["handoff_status"] == "closed"
    assert all(c["status"] not in ("awaiting_feedback", "escalated") for c in closed["cases"])
    reopened = say(client, sid, "One more question about my bill")
    assert reopened["handled_by"] == "bot" and reopened["conversation"]["handoff_status"] == "bot"


def test_invalid_handoff_transitions_rejected(client):
    sid = start(client)["session_id"]
    assert client.post(f"/api/v1/conversations/{sid}/handoff", json={"action": "release"}).status_code == 409
    assert client.post(f"/api/v1/conversations/{sid}/handoff", json={"action": "fly"}).status_code == 422
    assert client.post("/api/v1/conversations/chat-missing/handoff", json={"action": "take"}).status_code == 404


def test_max_attempts_escalates_chat_to_admin_inbox(client):
    sid = start(client)["session_id"]
    reply = say(client, sid, "My car's built-in connectivity module lost its connection after the update")
    case_id = reply["resolution"]["case_id"]
    for attempt in (1, 2):
        assert feedback(client, case_id, "not_solved")["next_action"] == "retry"
        client.post("/api/v1/resolve/retry", json={"case_id": case_id})
    assert feedback(client, case_id, "not_solved")["next_action"] == "escalated"
    chat = client.get(f"/api/v1/conversations/{sid}").json()
    assert chat["handoff_status"] == "needs_agent"
    assert any(m["role"] == "system" and (m["metadata"] or {}).get("handoff") == "needs_agent" for m in chat["messages"])
    queue = client.get("/api/v1/conversations", params={"handoff_status": "needs_agent"}).json()["items"]
    assert sid in {c["session_id"] for c in queue}


def test_fix_from_an_agent_goes_to_review_and_into_the_dataset(client):
    sid = start(client)["session_id"]
    case_id = say(client, sid, "My e-SIM QR code says already used when I scan it on my new phone")["resolution"]["case_id"]
    for _ in (1, 2):
        feedback(client, case_id, "not_solved")
        client.post("/api/v1/resolve/retry", json={"case_id": case_id})
    assert feedback(client, case_id, "not_solved")["next_action"] == "escalated"
    handoff(client, sid, "take", agent="Priya")
    for text in ("I've reissued your e-SIM profile.", "Please delete the old e-SIM and scan the new QR code."):
        client.post(f"/api/v1/conversations/{sid}/agent-message", json={"agent": "Priya", "message": text})
    closed = handoff(client, sid, "close", agent="Priya", resolved=True)
    assert closed["handoff_status"] == "closed"

    pending = client.get("/api/v1/candidates", params={"status": "pending_review", "origin": "agent_resolved"}).json()
    candidate = next(c for c in pending["items"] if c["case_id"] == case_id)
    assert "reissued your e-SIM" in candidate["proposed_resolution"] and candidate["customer_feedback"] == "solved_by_agent"
    approved = client.post(f"/api/v1/knowledge/{candidate['id']}/approve",
                           json={"reviewer": "lead", "intent": "sim_replacement"}).json()
    assert approved["article"]["status"] == "ACTIVE"
    assert approved["dataset_record_id"].startswith("TELCO-LIVE-")


def test_agent_close_without_a_reply_creates_no_candidate(client):
    sid = start(client)["session_id"]
    case_id = say(client, sid, "My SIM is not detected")["resolution"]["case_id"]
    handoff(client, sid, "take", agent="Priya")
    handoff(client, sid, "close", agent="Priya", resolved=True)
    pending = client.get("/api/v1/candidates", params={"origin": "agent_resolved", "page_size": 100}).json()["items"]
    assert case_id not in {c["case_id"] for c in pending}


def test_critical_issue_is_routed_to_an_agent_immediately(client):
    sid = start(client)["session_id"]
    reply = say(client, sid, "Someone hacked my account and changed my SIM")
    assert reply["resolution"]["analysis"]["severity"] == "critical"
    assert reply["conversation"]["handoff_status"] == "needs_agent"


def test_admin_approval_is_announced_in_the_customer_chat(client):
    sid = start(client)["session_id"]
    reply = say(client, sid, "My kids smartwatch location sharing stopped updating on the map")
    case_id = reply["resolution"]["case_id"]
    candidate_id = feedback(client, case_id, "solved")["candidate_id"]
    approved = client.post(f"/api/v1/knowledge/{candidate_id}/approve", json={
        "reviewer": "lead", "content": "Symptoms: watch location stale.\nResolution steps:\n1. Restart the watch and the paired phone."}).json()
    article = approved["article"]["article_id"]
    chat = client.get(f"/api/v1/conversations/{sid}").json()
    notices = [m for m in chat["messages"] if m["role"] == "system" and article in m["message"]]
    assert notices, "customer should be told their confirmed fix became trusted knowledge"


def test_customer_sees_queue_position_and_can_cancel(client):
    first = start(client, "First")["session_id"]
    second = start(client, "Second")["session_id"]
    assert handoff(client, first, "request")["queue_position"] >= 1
    pos_first = client.get(f"/api/v1/conversations/{first}").json()["queue_position"]
    pos_second = handoff(client, second, "request")["queue_position"]
    assert pos_second == pos_first + 1  # later requests queue behind earlier ones

    cancelled = handoff(client, second, "cancel")
    assert cancelled["handoff_status"] == "bot" and cancelled["queue_position"] is None
    assert any("keep helping you" in m["message"] for m in cancelled["messages"])
    # Nothing left to cancel.
    assert client.post(f"/api/v1/conversations/{second}/handoff", json={"action": "cancel"}).status_code == 409
    # Once an agent takes over, the customer can no longer cancel; the queue moves up.
    handoff(client, first, "take", agent="Priya")
    assert client.post(f"/api/v1/conversations/{first}/handoff", json={"action": "cancel"}).status_code == 409


def test_non_telecom_questions_are_politely_declined(client):
    sid = start(client)["session_id"]
    reply = say(client, sid, "My dog isn't taking food from past two days")
    assert reply["handled_by"] == "bot" and reply["resolution"] is None
    assert "telecom" in reply["assistant_message"]
    chat = reply["conversation"]
    assert chat["cases"] == []  # no case, so no feedback request and nothing for the review queue
    assert (chat["messages"][-1]["metadata"] or {}).get("type") == "out_of_scope"
    assert client.post("/api/v1/resolve", json={"session_id": sid, "complaint": "Give me a recipe for pasta"}).json()[
        "error"]["code"] == "OUT_OF_SCOPE"

    # Telecom questions in the same chat are still answered, and greetings get a friendly reply.
    assert say(client, sid, "My SIM is not detected")["resolution"]["citations"]
    thanks = say(client, sid, "Thank you so much")
    assert thanks["resolution"] is None and thanks["assistant_message"].startswith("You're welcome")
