"""Classification, product detection, entities, sentiment and severity."""
import pytest

from app.services.entity_extractor import extract_entities, mask_sensitive
from app.services.sentiment import analyze_sentiment, estimate_severity

CASES = [
    ("My broadband keeps disconnecting every evening", "broadband_disconnects"),
    ("I was charged twice on my bill", "billing_dispute"),
    ("My SIM is not detected by my phone", "sim_not_detected"),
    ("My mobile data is not working", "mobile_data_not_working"),
    ("My calls keep dropping", "call_drops"),
    ("I am not receiving OTP messages", "sms_not_received"),
    ("Roaming is not working while I am abroad", "roaming_not_working"),
    ("My phone supports 5G but 5G is not available", "5g_not_available"),
    ("Someone hacked my account", "account_security"),
    ("My recharge did not complete", "recharge_issue"),
]


@pytest.mark.parametrize("text,intent", CASES)
def test_intent_classification(services, db, text, intent):
    assert services.classifier.classify(db, text).intent == intent


def test_unknown_is_not_forced(services, db):
    analysis = services.classifier.classify(db, "Visual voicemail transcription stopped after the carrier settings update")
    assert analysis.intent == "unknown"
    assert analysis.intent_confidence == 0.0
    assert analysis.category == "Unclassified"


def test_category_and_product_detection(services, db):
    analysis = services.classifier.classify(db, "My broadband drops every evening around 8 PM")
    assert analysis.category == "Internet"
    assert analysis.subcategory == "Broadband"
    assert analysis.product == "broadband"
    assert analysis.domain_category == "CONNECTIVITY"


def test_guided_category_used_when_text_is_vague(services, db):
    analysis = services.classifier.classify(db, "it is not working properly", guided_category="Billing")
    assert analysis.intent == "unknown"
    assert analysis.category == "Billing"


def test_entity_extraction_reference_example():
    text = ("My broadband drops every evening around 8 PM and I have already restarted the router twice. "
            "I work from home and this is costing me.")
    found = {(e.type, e.value.lower()) for e in extract_entities(text)}
    assert ("time", "8 pm") in found
    assert ("frequency", "twice") in found
    assert ("device", "router") in found
    assert ("customer_context", "work from home") in found
    assert any(t == "troubleshooting" and "restarted the router" in v for t, v in found)


def test_sensitive_numbers_are_masked():
    entities = extract_entities("My account number is 9876543210123")
    refs = [e.value for e in entities if e.type == "account_reference"]
    assert refs and refs[0].endswith("0123") and "9876" not in refs[0]
    assert "9876543210123" not in mask_sensitive("call 9876543210123")


@pytest.mark.parametrize("text,label", [
    ("I need this fixed immediately, it is urgent", "urgent"),
    ("I already restarted it twice and it still keeps failing", "frustrated"),
    ("My wifi is not working", "negative"),
    ("I want information about available plans", "neutral"),
    ("Thanks, it is working now", "positive"),
])
def test_sentiment(text, label):
    assert analyze_sentiment(text).label == label


def test_severity_levels():
    sentiment = analyze_sentiment("neutral text")
    assert estimate_severity("Someone hacked my account", sentiment).label == "critical"
    text = "No internet at all and I work from home"
    assert estimate_severity(text, analyze_sentiment(text)).label == "high"
    assert estimate_severity("I want information about available plans", sentiment).label == "low"
    assert estimate_severity("My SMS is delayed", sentiment).label == "medium"
