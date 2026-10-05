"""Answers are worded correctly for each audience and built from the right sources."""
import csv
import re

import pytest
from sqlalchemy import select

from app.config import ROOT_DIR
from app.models import KnowledgeArticle
from app.services.grounded_templates import parse_kb, parse_ticket
from app.services.wording import PAST_TO_PRESENT, customer_version
from tests.conftest import resolve

ARTICLES = list(csv.DictReader(open(ROOT_DIR / "data" / "knowledge_base.csv", encoding="utf-8")))
# Internal wording that customers must never see.
AGENT_JARGON = re.compile(r"\b(the customer|approved|escalat\w*|route the|routed|ONT|agent follow-up)\b", re.I)


@pytest.mark.parametrize("row", ARTICLES, ids=[r["article_id"] for r in ARTICLES])
def test_every_article_words_each_step_for_customers(row):
    parsed = parse_kb(row["content"])
    assert parsed["steps"] and len(parsed["customer_steps"]) == len(parsed["steps"])
    for step in parsed["customer_steps"]:
        assert not AGENT_JARGON.search(step), step
        assert step[0].isupper() and step.endswith((".", "?"))


def test_resolved_ticket_notes_become_clean_instructions():
    note = ("Complaint: x\nResolution: Checked signal during calls, restarted the device and recorded whether "
            "incoming, outgoing, or both call directions were affected. If the issue remains, collect the device "
            "details and escalate.")
    steps = parse_ticket(note)["steps"]
    assert steps == ["Check signal during calls.",
                     "Restart the device and record whether incoming, outgoing, or both call directions were affected.",
                     "If the issue remains, collect the device details and escalate."]
    assert not any(s.split()[0].lower() in PAST_TO_PRESENT for s in steps)


def test_present_tense_is_left_alone():
    assert parse_ticket("Resolution: Verify the current plan and requested plan, and submit the change if eligible.")[
        "steps"] == ["Verify the current plan and requested plan.", "Submit the change if eligible."]


@pytest.mark.parametrize(("agent", "customer"), [
    ("Escalate if the SIM remains undetected.", "If it's still not working, let me know and our team will take it from there."),
    ("Record whether incoming or outgoing SMS is affected.", "Let me know whether incoming or outgoing SMS is affected."),
    ("Record the time and frequency of dropped calls for escalation if the issue continues.",
     "Note the time and frequency of dropped calls if the issue continues."),
    ("Check the payment status through the approved billing view.", "Check the payment status."),
    ("Treat as critical.", ""),
])
def test_fallback_customer_wording(agent, customer):
    assert customer_version(agent) == customer


@pytest.mark.parametrize(("question", "article"), [
    ("calls keep dropping", "KB-003"),
    ("5G is not showing on my phone", {"KB-008", "KB-036"}),
    ("no internet since morning", "KB-011"),
    ("I was charged twice on my bill this month", "KB-032"),
])
def test_clear_questions_are_answered_from_their_own_article(client, session_id, question, article):
    data = resolve(client, session_id, question)
    expected = {article} if isinstance(article, str) else article
    first = data["resolution"]["steps"][0]["citations"]
    assert expected & set(first), (question, first)


@pytest.mark.parametrize("question", [
    "My broadband drops every evening around 8 and I've already restarted the router twice",
    "my mobile data is not working", "my refund hasn't arrived", "I want to change my plan", "My SIM is not detected",
])
def test_customers_get_plain_wording_for_every_step(client, session_id, question):
    steps = resolve(client, session_id, question)["resolution"]["steps"]
    assert steps and all(step.get("customer_text") is not None for step in steps)
    for step in steps:
        if step["customer_text"]:
            assert not AGENT_JARGON.search(step["customer_text"]), step["customer_text"]


def test_tried_step_is_acknowledged_in_customer_wording(client, session_id):
    steps = resolve(client, session_id, "My broadband drops every evening around 8 and I've already "
                                        "restarted the router twice")["resolution"]["steps"]
    assert any(s["customer_text"] == "If you've already restarted your router, there's no need to do it again."
               for s in steps)


def test_unrelated_checklist_is_not_offered_for_a_hardware_fault(client, session_id):
    from app.services.embeddings import get_embedding_service
    if get_embedding_service().backend != "sentence_transformers":
        pytest.skip("the relevance bar is calibrated on the sentence-transformers scale")
    resolution = resolve(client, session_id, "my phone gets hot when using data")["resolution"]
    assert all(step["kind"] == "information_gathering" for step in resolution["steps"])
    assert resolution["steps"][0]["customer_text"].startswith("Tell me exactly what happens")


def test_existing_databases_receive_the_customer_wording(db, services):
    from app.ingestion import sync_seed_articles

    current = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.article_id == "KB-005",
                                                       KnowledgeArticle.is_latest.is_(True)))
    old_content = re.sub(r"\nCustomer steps:\n(?:\d+[.)].*\n)+", "\n", current.content)
    stale = services.knowledge.update_article(db, "KB-005", {"content": old_content, "change_note": "old seed"},
                                              editor="seed")
    assert not parse_kb(stale.content)["customer_steps"]
    result = sync_seed_articles(db, services.knowledge, ROOT_DIR / "data" / "knowledge_base.csv")
    assert result["updated"] >= 1
    latest = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.article_id == "KB-005",
                                                      KnowledgeArticle.is_latest.is_(True)))
    assert latest.version == stale.version + 1 and len(parse_kb(latest.content)["customer_steps"]) == 4


@pytest.mark.parametrize("question", ["roaming not working in France", "I was charged twice on my bill this month",
                                      "5G is not showing on my phone", "wifi is not working at home"])
def test_answer_follows_one_article_without_repeats(client, session_id, question):
    steps = resolve(client, session_id, question)["resolution"]["steps"]
    articles = {c for step in steps for c in step["citations"] if c.startswith("KB-")}
    first = next(c for c in steps[0]["citations"] if c.startswith("KB-"))
    assert all(first in step["citations"] for step in steps), (question, [s["citations"] for s in steps])
    texts = [step["customer_text"] for step in steps]
    assert len(texts) == len(set(texts)) and articles


def _questions(name: str) -> list[str]:
    return [r["complaint"] for r in csv.DictReader(open(ROOT_DIR / "data" / name, encoding="utf-8"))]


def test_training_examples_are_independent_of_the_evaluation_questions():
    """Examples that resemble a test or practice question would inflate the scores, so none may."""
    import sys

    from app.utils.text import jaccard
    sys.path.insert(0, str(ROOT_DIR / "scripts"))
    from seed_intent_examples import EXTRA_EXAMPLES
    held = _questions("eval_realistic_complaints.csv") + _questions("tune_realistic_complaints.csv")
    close = [(ex, q) for examples in EXTRA_EXAMPLES.values() for ex in examples for q in held if jaccard(ex, q) >= 0.5]
    assert not close, close[:5]
    tune2 = _questions("tune2_realistic_complaints.csv")
    assert not [(p, q) for p in tune2 for q in _questions("eval_realistic_complaints.csv") if jaccard(p, q) >= 0.5]


@pytest.mark.parametrize(("a", "b", "close"), [
    ("disconnceting", "disconnecting", True), ("evennig", "evening", True), ("recieve", "receive", True),
    ("router", "routers", True), ("signal", "single", False), ("refund", "refund", False),
])
def test_one_edit_apart(a, b, close):
    from app.utils.text import one_edit_apart
    assert one_edit_apart(a, b) is close


@pytest.mark.parametrize(("question", "intent"), [
    ("my broadband keeps disconnceting every evennig", "broadband_disconnects"),   # typos corrected
    ("travelling in Portugal and there is no signal on my phone", "roaming_not_working"),  # context beats symptom
    ("I was charged twice on my bill this month", "billing_dispute"),               # a specific dispute phrase stays
    ("my calls keep getting disconnected", "call_drops"),                            # the named area (calls) wins
])
def test_classifier_handles_real_wording(db, services, question, intent):
    assert services.classifier.classify(db, question).intent == intent


def test_classifier_reads_sentiment_from_the_original_words(db, services):
    from app.services.sentiment import analyze_sentiment
    text = "my broadband keeps disconnceting and I'm really frustrated"
    analysis = services.classifier.classify(db, text)
    assert analysis.intent == "broadband_disconnects" and analysis.sentiment == analyze_sentiment(text).label


def test_approved_new_wording_is_recognised_next_time(client, db, services, session_id):
    """A new way of describing an issue, confirmed by a customer and approved by a reviewer, is learned."""
    question = "a little x keeps showing where the bars on my mobile should be"
    assert services.classifier.classify(db, question).intent != "no_signal"  # not recognised yet
    first = resolve(client, session_id, question)
    candidate_id = client.post("/api/v1/feedback", json={"case_id": first["case_id"], "outcome": "solved"}).json()["candidate_id"]
    approved = client.post(f"/api/v1/knowledge/{candidate_id}/approve",
                           json={"reviewer": "qa-lead", "intent": "no_signal"}).json()
    assert approved["status"] == "approved" and approved["learned_example"] is True
    db.expire_all()
    assert services.classifier.classify(db, question).intent == "no_signal"  # learned
    again = resolve(client, f"{session_id}-again", question)
    assert again["analysis"]["intent"] == "no_signal"
    first_article = next(c for c in again["resolution"]["steps"][0]["citations"] if c.startswith("KB-"))
    by_id = {s["source_id"]: s for s in again["retrieval"]["sources"]}
    assert by_id[first_article]["intent"] == "no_signal"  # answered from a no-signal article (KB-005 or the approved one)
