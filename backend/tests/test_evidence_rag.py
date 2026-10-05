"""Evidence scoring, thresholds, RAG grounding guard and LLM fallback."""
from app.config import get_settings
from app.services.evidence import EvidenceScoringService
from app.services.llm_provider import LLMError, LLMProvider
from app.services.rag import GROUNDING_RULES, SYSTEM_PROMPT, RAGService
from app.services.retrieval import ScoredSource
from app.services.taxonomy import taxonomy_service

KB_TEXT = ("Symptoms: Broadband drops.\nResolution steps:\n1. Check router/ONT status indicators.\n"
           "2. Restart the equipment.\nEscalate when: Drops continue.\nCaution: Do not promise compensation.")


def src(source_id="KB-010", intent="broadband_disconnects", sem=0.9, rr=0.9, meta=1.0, final=0.9, content=KB_TEXT,
        source_type="knowledge_base", quality=1.0):
    return ScoredSource(chunk_id=f"{source_id}:0", source_id=source_id, source_type=source_type, title="Broadband drops",
                        content=content, intent=intent, category="Broadband", product="broadband", quality=quality,
                        extra={}, semantic_raw=0.7, semantic_score=sem, keyword_score=0.5, metadata_score=meta,
                        hybrid_score=final, reranker_score=rr, final_score=final)


def test_thresholds_single_source_of_truth():
    s = get_settings()
    assert s.classify_evidence(0.70) == "known"
    assert s.classify_evidence(0.69) == "uncertain"
    assert s.classify_evidence(0.45) == "uncertain"
    assert s.classify_evidence(0.44) == "unknown"


def test_evidence_formula(db):
    taxonomy = taxonomy_service.get(db)
    result = EvidenceScoringService().score([src(), src("KB-031", final=0.8)], "broadband_disconnects", taxonomy)
    s = get_settings()
    c = result.components
    expected = (s.evidence_semantic_weight * c["semantic"] + s.evidence_reranker_weight * c["reranker"]
                + s.evidence_intent_weight * c["intent_match"] + s.evidence_source_quality_weight * c["source_quality"]
                + s.evidence_metadata_weight * c["metadata"])
    assert abs(result.score - expected) < 1e-9
    assert result.status == "known"
    assert result.relevant_sources == 2


def test_no_sources_is_unknown(db):
    result = EvidenceScoringService().score([], "broadband_disconnects", taxonomy_service.get(db))
    assert result.status == "unknown" and result.score == 0.0


def test_intent_mismatch_lowers_evidence(db):
    taxonomy = taxonomy_service.get(db)
    service = EvidenceScoringService()
    match = service.score([src()], "broadband_disconnects", taxonomy)
    related = service.score([src()], "broadband_slow", taxonomy)
    unrelated = service.score([src()], "billing_dispute", taxonomy)
    assert match.score > related.score > unrelated.score
    assert related.intent_match == 0.25 and unrelated.intent_match == 0.0


def test_grounding_prompt_contains_required_rules():
    for sentence in ("Use only the supplied evidence.", "Do not invent unsupported facts.",
                     "If the evidence is insufficient, say that the evidence is insufficient.",
                     "Do not create fake sources or citations."):
        assert sentence in GROUNDING_RULES
        assert sentence in SYSTEM_PROMPT


def test_guard_removes_fake_citations_unsupported_steps_and_prices():
    rag = RAGService.__new__(RAGService)
    rag.settings = get_settings()
    raw = {"summary": "Fix [KB-999]", "diagnosis": "Router fault [KB-010]",
           "steps": [{"text": "Check router/ONT status indicators.", "citations": ["KB-010", "KB-404"]},
                     {"text": "Offer a $50 credit for the outage.", "citations": ["KB-010"]},
                     {"text": "Replace the customer's fibre cable immediately.", "citations": ["KB-010"]},
                     {"text": "Restart the equipment.", "citations": []}],
           "warnings": ["Do not promise compensation. [KB-010]"], "escalation": False, "insufficient_evidence": False}
    cleaned, report = rag.guard(raw, [src()], "known")
    texts = [s["text"] for s in cleaned["steps"]]
    assert texts == ["Check router/ONT status indicators."]
    assert cleaned["steps"][0]["citations"] == ["KB-010"]
    assert "KB-999" in report["removed_citations"] and "KB-404" in report["removed_citations"]
    assert "[KB-999]" not in cleaned["summary"]
    assert len(report["removed_steps"]) == 3


def test_guard_downgrades_when_nothing_is_grounded():
    rag = RAGService.__new__(RAGService)
    rag.settings = get_settings()
    cleaned, _ = rag.guard({"summary": "x", "steps": [{"text": "Invented step", "citations": ["FAKE-1"]}]}, [src()], "known")
    assert cleaned["insufficient_evidence"] is True
    assert all(s["kind"] == "information_gathering" for s in cleaned["steps"])


class FailingProvider(LLMProvider):
    name = "gemini"
    is_llm = True

    def complete_json(self, *args, **kwargs):
        raise LLMError("timeout")


def _generate(rag, mode="known", sources=None):
    return rag.generate(complaint="broadband drops", analysis={"intent": "broadband_disconnects", "severity": "medium"},
                        mode=mode, sources=sources if sources is not None else [src()],
                        evidence={"score": 0.9, "status": mode, "top_similarity": 0.9, "intent_match": 1.0},
                        memory_summary="", troubleshooting=[], customer_context=[], attempt=1, previous_steps=[],
                        additional_info=None, follow_up_question=None)


def test_llm_failure_falls_back_to_grounded_template():
    answer = _generate(RAGService(FailingProvider()))
    assert answer.generator == "grounded_template_fallback"
    assert answer.steps and all(s["citations"] == ["KB-010"] for s in answer.steps)
    assert any("LLM was unavailable" in w for w in answer.warnings)


def test_template_with_no_evidence_says_insufficient():
    from app.services.llm_provider import MockProvider
    answer = _generate(RAGService(MockProvider()), mode="unknown", sources=[])
    assert answer.insufficient_evidence is True
    assert "evidence is insufficient" in answer.summary.lower()
    assert answer.citations == []


def test_retry_template_excludes_previous_steps():
    from app.services.grounded_templates import build_answer
    payload = {"mode": "known", "analysis": {"intent_display": "x", "severity": "medium"},
               "evidence": {"score": 0.8}, "thresholds": {"known": 0.7, "unknown": 0.45},
               "sources": [{"id": "KB-010", "type": "knowledge_base", "title": "t", "content": KB_TEXT}],
               "previous_steps": ["Check router/ONT status indicators."], "attempt": 2}
    texts = [s["text"] for s in build_answer(payload)["steps"]]
    assert "Check router/ONT status indicators." not in texts
    assert "Restart the equipment." in texts


def test_general_checklists_do_not_count_as_evidence(db):
    taxonomy = taxonomy_service.get(db)
    general = src("KB-037", intent="unknown")
    general.extra = {"general": True}
    assert EvidenceScoringService().score([general], "unknown", taxonomy).status == "unknown"
    assert EvidenceScoringService().score([general], "unknown", taxonomy).score == 0.0
