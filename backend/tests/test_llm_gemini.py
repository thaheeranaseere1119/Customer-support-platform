"""AI mode: the Gemini provider's HTTP contract, its failure handling, and the grounding guard on its output.

The Gemini API is simulated (no key, no network); `scripts/verify_llm.py` checks the live path once a key is set.
"""
import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import get_settings
from app.services import llm_provider
from app.services.classifier import ClassificationService
from app.services.embeddings import get_embedding_service
from app.services.llm_provider import GeminiProvider, LLMError
from app.services.rag import SYSTEM_PROMPT, RAGService
from tests.test_evidence_rag import _generate


def gemini(monkeypatch, *responses):
    """A GeminiProvider whose HTTP calls return `responses` in order; returns (provider, captured requests)."""
    provider = GeminiProvider()
    provider.settings = get_settings().model_copy(update={"gemini_api_key": SecretStr("test-key"),
                                                          "gemini_model": "gemini-test"})
    calls, queue = [], list(responses)

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json})
        status, body = queue.pop(0)
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm_provider.httpx, "post", fake_post)
    monkeypatch.setattr(llm_provider, "RETRY_DELAY_SECONDS", 0)
    return provider, calls


def reply(obj, fenced=False) -> dict:
    text = json.dumps(obj)
    return {"candidates": [{"content": {"parts": [{"text": f"```json\n{text}\n```" if fenced else text}]}}]}


def test_request_shape_and_json_parsing(monkeypatch):
    provider, calls = gemini(monkeypatch, (200, reply({"summary": "ok", "steps": []})))
    assert provider.complete_json("rag_answer", "system rules", "user prompt", {}) == {"summary": "ok", "steps": []}
    call = calls[0]
    assert call["url"].endswith("/models/gemini-test:generateContent")
    assert call["headers"]["x-goog-api-key"] == "test-key"  # the key travels in a header, never in the URL
    assert call["json"]["systemInstruction"]["parts"][0]["text"] == "system rules"
    assert call["json"]["contents"][0]["parts"][0]["text"] == "user prompt"
    assert call["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_code_fenced_json_is_accepted(monkeypatch):
    provider, _ = gemini(monkeypatch, (200, reply({"intent": "unknown", "confidence": 0.1}, fenced=True)))
    assert provider.complete_json("classify", "s", "u", {})["intent"] == "unknown"


def test_transient_error_is_retried_once(monkeypatch):
    provider, calls = gemini(monkeypatch, (503, {}), (200, reply({"summary": "ok"})))
    assert provider.complete_json("rag_answer", "s", "u", {}) == {"summary": "ok"}
    assert len(calls) == 2


@pytest.mark.parametrize("responses", [
    [(400, {"error": {"message": "bad request"}})],              # not retried
    [(429, {}), (429, {})],                                      # still rate limited after the retry
    [(200, {"promptFeedback": {"blockReason": "SAFETY"}})],      # blocked: no candidates
    [(200, {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})],
    [(200, reply(["a", "list"]))],                               # JSON, but not an object
])
def test_failures_raise_llm_error(monkeypatch, responses):
    provider, _ = gemini(monkeypatch, *responses)
    with pytest.raises(LLMError):
        provider.complete_json("rag_answer", "s", "u", {})


def test_missing_key_never_calls_the_api(monkeypatch):
    provider, calls = gemini(monkeypatch)
    provider.settings = provider.settings.model_copy(update={"gemini_api_key": None})
    with pytest.raises(LLMError):
        provider.complete_json("rag_answer", "s", "u", {})
    assert calls == []


def test_gemini_answer_is_grounded_and_invented_content_removed(monkeypatch):
    answer_json = {
        "summary": "Evening drops match a known pattern [KB-010].", "diagnosis": "Line or equipment instability.",
        "steps": [
            {"text": "Check router/ONT status indicators.", "citations": ["KB-010"]},
            {"text": "Offer a 20% bill credit for the inconvenience.", "citations": ["KB-010"]},  # invented figure
            {"text": "Replace the customer's fibre cable.", "citations": ["KB-999"]},           # fake source
        ],
        "warnings": [], "escalation": False, "escalation_reason": None, "insufficient_evidence": False,
    }
    provider, calls = gemini(monkeypatch, (200, reply(answer_json)))
    answer = _generate(RAGService(provider))
    assert answer.generator == "gemini"
    assert [s["text"] for s in answer.steps] == ["Check router/ONT status indicators."]
    assert all(s["citations"] == ["KB-010"] for s in answer.steps)
    assert len(answer.guard_report["removed_steps"]) == 2
    assert [c["source_id"] for c in answer.citations] == ["KB-010"]
    sent = calls[0]["json"]
    assert sent["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT
    assert "[KB-010]" in sent["contents"][0]["parts"][0]["text"]  # the evidence is in the prompt


def test_gemini_failure_falls_back_to_the_template(monkeypatch):
    provider, _ = gemini(monkeypatch, (500, {}), (500, {}))
    answer = _generate(RAGService(provider))
    assert answer.generator == "grounded_template_fallback"
    assert answer.steps and any("LLM was unavailable" in w for w in answer.warnings)


def test_gemini_classification_must_stay_inside_the_taxonomy(monkeypatch, db):
    provider, _ = gemini(monkeypatch, (200, reply({"intent": "broadband_disconnects", "confidence": 0.92})),
                         (200, reply({"intent": "made_up_intent", "confidence": 0.99})))
    classifier = ClassificationService(get_embedding_service(), provider)
    first = classifier.classify(db, "My connection keeps cutting out at night")
    assert (first.intent, first.classification_method) == ("broadband_disconnects", "llm")
    second = classifier.classify(db, "My connection keeps cutting out at night")
    assert second.classification_method != "llm" and second.intent != "made_up_intent"
