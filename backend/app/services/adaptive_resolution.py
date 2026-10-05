"""Adaptive resolution workflow (the single pipeline used by guided, free-text,
voice and conversation input).

Complaint -> understanding -> memory -> embedding -> hybrid retrieval -> rerank ->
evidence scoring -> KNOWN: grounded RAG + citations
                 -> UNCERTAIN/UNKNOWN: candidate resolution -> feedback ->
                    YES: candidate knowledge (human review) | PARTIAL: more info + retry |
                    NO: alternative evidence retry ... -> escalate after MAX_RESOLUTION_ATTEMPTS.
Every attempt is persisted; nothing is overwritten.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CandidateCase, Feedback, ResolutionAttempt, SupportCase
from app.models._common import utcnow
from app.services import handoff
from app.services.classifier import Analysis, ClassificationService
from app.services.embeddings import EmbeddingService
from app.services.emerging_issue import EmergingIssueService
from app.services.evidence import EvidenceScoringService
from app.services.knowledge_evolution import KnowledgeService, is_dataset_query
from app.services.memory import MemoryService
from app.services.rag import RAGService
from app.services.reranker import RerankerService
from app.services.retrieval import RetrievalFilters, RetrievalService, ScoredSource
from app.services.scope import (
    CLARIFY_REPLY,
    OUT_OF_SCOPE_REPLY,
    is_telecom_question,
    is_vague_problem,
    small_talk_reply,
)
from app.services.taxonomy import taxonomy_service
from app.utils.errors import ConflictError, NotFoundError, OutOfScope
from app.utils.logging import log_event, new_request_id, request_id_var, short_id
from app.utils.text import truncate

logger = logging.getLogger(__name__)

STAGES = [
    ("understanding", "Understanding"),
    ("embedding", "Embedding"),
    ("retrieving", "Retrieving"),
    ("reranking", "Reranking"),
    ("checking_evidence", "Checking evidence"),
    ("generating", "Generating"),
    ("citing", "Citing"),
    ("complete", "Complete"),
]
STAGE_LABELS = dict(STAGES)
StageCallback = Callable[[dict], None]

STATUS_LABELS = {
    "known": "VERIFIED RESOLUTION",
    "uncertain": "CANDIDATE RESOLUTION - NOT VERIFIED",
    "unknown": "NEW ISSUE - CANDIDATE RESOLUTION",
}


class StageTracker:
    def __init__(self, callback: StageCallback | None):
        self.callback = callback
        self.stages: list[dict] = []
        self._current: tuple[str, float] | None = None

    def start(self, name: str) -> None:
        self._current = (name, time.perf_counter())
        if self.callback:
            self.callback({"type": "stage", "name": name, "label": STAGE_LABELS[name], "status": "running"})

    def finish(self, status: str = "success", detail: str = "") -> None:
        assert self._current is not None
        name, started = self._current
        record = {"name": name, "label": STAGE_LABELS[name], "status": status,
                  "duration_ms": round((time.perf_counter() - started) * 1000, 2), "detail": detail}
        self.stages.append(record)
        self._current = None
        if self.callback:
            self.callback({"type": "stage", **record})

    def fail(self, detail: str) -> None:
        if self._current:
            self.finish("error", detail)


@dataclass
class Services:
    embeddings: EmbeddingService
    reranker: RerankerService
    retrieval: RetrievalService
    evidence: EvidenceScoringService
    classifier: ClassificationService
    rag: RAGService
    memory: MemoryService
    knowledge: KnowledgeService
    emerging: EmergingIssueService


def public_sources(sources: list, citations: list[dict], limit: int) -> list[dict]:
    """Top-N sources plus any cited source ranked lower, so every citation is inspectable."""
    shown = sources[:limit]
    ids = {x.source_id for x in shown}
    cited = {c["source_id"] for c in citations}
    shown += [x for x in sources[limit:] if x.source_id in cited and x.source_id not in ids]
    return [x.to_public() for x in shown]


def assistant_reply(answer, attempt_number: int) -> str:
    """Chat transcript text: summary, numbered cited steps and the feedback question."""
    lines = [answer.summary if attempt_number == 1 else f"Attempt {attempt_number}: {answer.summary}"]
    for i, step in enumerate(answer.steps, 1):
        cites = " ".join(f"[{c}]" for c in step["citations"])
        tried = " (customer already tried)" if step.get("already_attempted") else ""
        lines.append(f"{i}. {step['text']}{tried} {cites}".rstrip())
    if answer.escalation and answer.escalation_reason:
        lines.append(f"Escalation: {answer.escalation_reason}")
    if answer.follow_up_question:
        lines.append(answer.follow_up_question)
    lines.append("Did this solve the problem?")
    return "\n".join(lines)


def attempt_to_dict(a: ResolutionAttempt) -> dict:
    return {
        "id": a.id, "attempt_number": a.attempt_number, "status": a.status, "is_candidate": a.is_candidate,
        "insufficient_evidence": a.insufficient_evidence, "summary": a.summary, "diagnosis": a.diagnosis,
        "steps": a.steps, "warnings": a.warnings, "escalation": a.escalation, "escalation_reason": a.escalation_reason,
        "follow_up_question": a.follow_up_question, "citations": a.citations, "sources": a.sources,
        "evidence": a.evidence, "evidence_score": round(a.evidence_score, 4), "query": a.query,
        "additional_info": a.additional_info, "excluded_source_ids": a.excluded_source_ids, "generator": a.generator,
        "pipeline": a.pipeline, "retrieval_latency_ms": a.retrieval_latency_ms, "llm_latency_ms": a.llm_latency_ms,
        "total_latency_ms": a.total_latency_ms, "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def case_summary(c: SupportCase) -> dict:
    return {"case_id": c.id, "session_id": c.session_id, "complaint": c.complaint, "intent": c.intent,
            "intent_display": (c.analysis or {}).get("intent_display", c.intent), "category": c.category,
            "product": c.product, "severity": c.severity, "sentiment": c.sentiment,
            "evidence_score": round(c.evidence_score, 4), "evidence_status": c.evidence_status, "status": c.status,
            "current_attempt": c.current_attempt, "escalated": c.escalated, "input_mode": c.input_mode,
            "latency_ms": c.latency_ms, "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None}


class AdaptiveResolutionService:
    def __init__(self, services: Services):
        self.s = services
        self.settings = get_settings()

    def _topic(self, analysis: Analysis, taxonomy) -> str | None:
        """Top-level topic of the question: the detected category, else the closest intent's category as a hint."""
        if analysis.category and analysis.category != "Unclassified":
            return analysis.category
        best = analysis.candidates[0] if analysis.candidates else None
        info = taxonomy.intents.get(best["intent"]) if best else None
        if info and best["similarity"] >= self.settings.topic_hint_min_similarity:
            return taxonomy.top_category(info.support_category)
        return None

    def _trusted_intent(self, analysis: Analysis) -> str | None:
        if analysis.intent and analysis.intent != "unknown" and \
                analysis.intent_confidence >= self.settings.trusted_intent_confidence:
            return analysis.intent
        return None

    def _anchor_articles(self, db: Session, sources: list[ScoredSource], intent: str, query: str, analysis: Analysis,
                         taxonomy, exclude_ids: set[str], qvec) -> list[ScoredSource]:
        """Put the help article(s) for a confidently classified issue type first; fetch them if search missed them."""
        s = self.s
        floor = self.settings.trusted_article_min_semantic

        def own(src: ScoredSource) -> bool:
            return (src.source_type == "knowledge_base" and src.intent == intent and not (src.extra or {}).get("general")
                    and src.semantic_score >= floor)

        if not any(own(x) for x in sources):
            extra = s.retrieval.search(
                db, query, intent=intent, category=analysis.category, product=analysis.product, taxonomy=taxonomy,
                filters=RetrievalFilters(exclude_source_ids=exclude_ids, source_types={"knowledge_base"}), top_k=5,
                query_vector=qvec)
            known = {x.source_id for x in sources}
            sources = sources + [x for x in extra.sources if own(x) and x.source_id not in known]
        return [x for x in sources if own(x)] + [x for x in sources if not own(x)]

    # ================================================================ core run
    def _run(self, db: Session, *, request_id: str, session, complaint: str, analysis: Analysis, effective_query: str,
             guided_category: str | None, attempt_number: int, exclude_ids: set[str], previous_steps: list[str],
             additional_info: str | None, tracker: StageTracker, memory_context, widen: bool) -> dict:
        s = self.s
        settings = self.settings
        taxonomy = taxonomy_service.get(db)

        # -- embedding ------------------------------------------------------
        tracker.start("embedding")
        qvec, embed_detail, embed_status = None, f"{s.embeddings.backend} ({s.embeddings.model_name})", "success"
        try:
            qvec = s.embeddings.embed_one(effective_query)
        except Exception as exc:
            embed_status, embed_detail = "warning", f"embedding failed ({exc.__class__.__name__}); keyword-only retrieval"
        tracker.finish(embed_status, embed_detail)

        # -- retrieval -------------------------------------------------------
        tracker.start("retrieving")
        filters = RetrievalFilters(guided_category=None if widen else guided_category, exclude_source_ids=exclude_ids)
        outcome = s.retrieval.search(
            db, effective_query, intent=analysis.intent, category=analysis.category, product=analysis.product,
            taxonomy=taxonomy, filters=filters, top_k=settings.top_k * (2 if widen else 1), query_vector=qvec,
        )
        tracker.finish("warning" if outcome.degraded_reasons else "success",
                       f"{len(outcome.sources)} sources from {outcome.candidates_considered} candidates via "
                       f"{outcome.vector_backend} + BM25" + (f"; {', '.join(outcome.degraded_reasons)}" if outcome.degraded_reasons else ""))

        # -- reranking -------------------------------------------------------
        tracker.start("reranking")
        sources, rerank_method = s.reranker.rerank(effective_query, outcome.sources)
        named = bool(analysis.category and analysis.category != "Unclassified")
        sources = s.retrieval.prefer_topic(sources, self._topic(analysis, taxonomy), taxonomy, strict=named)
        trusted = self._trusted_intent(analysis)
        # Confidence is measured on the best-matching sources; the answer is written from the issue type's article.
        answer_order = (self._anchor_articles(db, sources, trusted, effective_query, analysis, taxonomy, exclude_ids, qvec)
                        if trusted else sources)
        sources = sources + [x for x in answer_order if x not in sources]
        tracker.finish("success" if rerank_method in ("cross_encoder", "none") else "warning",
                       "cross-encoder reranking" if rerank_method == "cross_encoder" else
                       ("no sources to rerank" if rerank_method == "none" else "reranker unavailable: hybrid score used"))

        # -- evidence --------------------------------------------------------
        tracker.start("checking_evidence")
        assessment = s.evidence.score(sources, analysis.intent, taxonomy)
        mode = assessment.status
        tracker.finish("success" if mode == "known" else "warning",
                       f"evidence {assessment.score:.2f} -> {mode.upper()}")

        # -- generation ------------------------------------------------------
        tracker.start("generating")
        general_floor = s.embeddings.general_checklist_threshold()

        def fitting(items: list[ScoredSource]) -> list[ScoredSource]:
            """A general checklist must be about the topic the question names (heat on 'mobile data' is not a
            calling problem); with no topic named, the relevance bar alone decides."""
            if not named:
                return items
            return [x for x in items if not (x.extra or {}).get("general")
                    or taxonomy.top_category(x.category) == analysis.category]

        selected = s.rag.select_sources(mode, fitting(answer_order), analysis.intent, trusted_intent=trusted,
                                        general_min_semantic=general_floor)
        if not selected and mode != "known":
            # No issue-specific evidence qualifies: look up the closest general checklist so the
            # customer still receives best-suitable, cited guidance (labelled as general).
            general = s.retrieval.search(
                db, effective_query, intent=analysis.intent, category=analysis.category, product=analysis.product,
                taxonomy=taxonomy, filters=RetrievalFilters(exclude_source_ids=exclude_ids, general_only=True),
                top_k=5, query_vector=qvec)
            ranked, _ = s.reranker.rerank(effective_query, general.sources)
            selected = s.rag.select_sources(mode, fitting(ranked), analysis.intent, general_min_semantic=general_floor)
            sources = sources + [x for x in selected if x.source_id not in {y.source_id for y in sources}]
        info = taxonomy.intents.get(analysis.intent)
        follow_up = None
        if mode != "known":
            follow_up = (info.clarifying_question if info and info.clarifying_question else
                         "Can you describe exactly what happens, when it started, and any message shown on the device?")
        elif info and info.clarifying_question and not any(e["type"] in ("time", "time_of_day", "frequency", "duration")
                                                           for e in analysis.entities + analysis.memory_entities):
            follow_up = info.clarifying_question
        troubleshooting = s.memory.troubleshooting(memory_context, analysis)
        customer_context = [e["value"] for e in analysis.entities + analysis.memory_entities if e["type"] == "customer_context"]
        answer = s.rag.generate(
            complaint=complaint, analysis=analysis.to_dict(), mode=mode, sources=selected,
            evidence={"score": assessment.score, "status": mode, "top_similarity": assessment.top_similarity,
                      "intent_match": assessment.intent_match},
            memory_summary=memory_context.summary, troubleshooting=troubleshooting, customer_context=customer_context,
            attempt=attempt_number, previous_steps=previous_steps, additional_info=additional_info,
            follow_up_question=follow_up,
        )
        if mode == "known" and answer.insufficient_evidence:
            mode = "uncertain"  # the grounding guard could not verify any step
        tracker.finish("success" if not answer.insufficient_evidence else "warning",
                       f"{answer.generator}: {sum(1 for x in answer.steps if x['kind'] == 'resolution')} grounded step(s)"
                       + (f", {len(answer.guard_report.get('removed_steps', []))} removed by guard"
                          if answer.guard_report.get("removed_steps") else ""))

        # -- citations -------------------------------------------------------
        tracker.start("citing")
        tracker.finish("success" if answer.citations or answer.insufficient_evidence else "warning",
                       f"{len(answer.citations)} citation(s) verified against retrieved sources")

        return {"mode": mode, "assessment": assessment, "sources": sources, "outcome": outcome,
                "rerank_method": rerank_method, "answer": answer, "qvec": qvec}

    # ============================================================ responses
    def _response(self, *, request_id: str, case: SupportCase, attempt: ResolutionAttempt, analysis: dict, run: dict,
                  tracker: StageTracker, memory_context, session, total_ms: float) -> dict:
        assessment = run["assessment"]
        outcome = run["outcome"]
        answer = run["answer"]
        mode = run["mode"]
        settings = self.settings
        unknown = None
        if mode == "unknown":
            unknown = {"headline": "NEW ISSUE DETECTED",
                       "message": "This looks like a new issue: no verified article covers it yet, so the closest relevant guidance is shown.",
                       "evidence_score": round(assessment.score, 4), "top_similarity": round(assessment.top_similarity, 4),
                       "intent_match": round(assessment.intent_match, 4)}
        can_retry = case.current_attempt < settings.max_resolution_attempts and case.status not in ("resolved", "candidate_submitted", "escalated")
        return {
            "request_id": request_id, "case_id": case.id, "session_id": case.session_id, "mode": settings.mode_label,
            "case_status": case.status,
            "attempt": {"attempt_number": attempt.attempt_number, "max_attempts": settings.max_resolution_attempts,
                        "can_retry": can_retry},
            "analysis": analysis,
            "retrieval": {
                "evidence_score": round(assessment.score, 4), "evidence": assessment.to_dict(),
                "sources": public_sources(run["sources"], answer.citations, settings.sources_returned),
                "semantic_used": outcome.semantic_used, "keyword_used": outcome.keyword_used,
                "vector_backend": outcome.vector_backend, "reranker_method": run["rerank_method"],
                "filter_relaxed": outcome.filter_relaxed, "degraded_reasons": outcome.degraded_reasons,
                "candidates_considered": outcome.candidates_considered,
                "excluded_source_ids": list(attempt.excluded_source_ids or []),
                "latency_ms": round(outcome.latency_ms, 2),
            },
            "resolution": {
                "status": mode, "is_candidate": mode != "known", "label": STATUS_LABELS[mode],
                "summary": answer.summary, "diagnosis": answer.diagnosis, "steps": answer.steps,
                "warnings": answer.warnings, "escalation": answer.escalation, "escalation_reason": answer.escalation_reason,
                "insufficient_evidence": answer.insufficient_evidence, "follow_up_question": answer.follow_up_question,
                "generator": answer.generator, "guard_report": answer.guard_report,
            },
            "citations": answer.citations,
            "unknown_issue": unknown,
            "memory": {"summary": memory_context.summary if memory_context else "", "used": bool(analysis.get("used_memory")),
                       "state": dict(session.memory or {}), "turns": len(memory_context.turns) if memory_context else 0},
            "pipeline": tracker.stages,
            "latency_ms": round(total_ms, 2),
        }

    def _persist_attempt(self, db: Session, case: SupportCase, attempt_number: int, run: dict, query: str,
                         additional_info: str | None, exclude_ids: set[str], tracker: StageTracker, total_ms: float) -> ResolutionAttempt:
        answer = run["answer"]
        assessment = run["assessment"]
        attempt = ResolutionAttempt(
            case_id=case.id, attempt_number=attempt_number, status=run["mode"], is_candidate=run["mode"] != "known",
            insufficient_evidence=answer.insufficient_evidence, summary=answer.summary, diagnosis=answer.diagnosis,
            steps=answer.steps, warnings=answer.warnings, escalation=answer.escalation,
            escalation_reason=answer.escalation_reason, follow_up_question=answer.follow_up_question,
            citations=answer.citations,
            sources=public_sources(run["sources"], answer.citations, self.settings.sources_returned),
            evidence=assessment.to_dict(), evidence_score=assessment.score, query=query, additional_info=additional_info,
            excluded_source_ids=sorted(exclude_ids), generator=answer.generator, pipeline=tracker.stages,
            retrieval_latency_ms=round(run["outcome"].latency_ms, 2), llm_latency_ms=answer.llm_latency_ms,
            total_latency_ms=round(total_ms, 2),
        )
        db.add(attempt)
        db.flush()
        return attempt

    def _detect_emerging(self, db: Session) -> None:
        try:
            with db.begin_nested():
                self.s.emerging.detect(db)
        except Exception:
            logger.exception("Emerging issue detection failed (non-fatal)")

    # ============================================================== resolve
    def resolve(self, db: Session, *, session_id: str, complaint: str, guided_category: str | None = None,
                input_mode: str = "free_text", on_stage: StageCallback | None = None) -> dict:
        request_id = request_id_var.get() or new_request_id()
        started = time.perf_counter()
        tracker = StageTracker(on_stage)
        s = self.s

        tracker.start("understanding")
        try:
            session = s.memory.get_or_create(db, session_id)
            memory_context = s.memory.load(db, session)
            analysis = s.classifier.classify(db, complaint, guided_category)
            effective_query, analysis = s.memory.apply(memory_context, complaint, analysis, taxonomy_service.get(db))
            s.memory.add_message(db, session, "user", complaint, {"input_mode": input_mode, "guided_category": guided_category})
            # Only telecom questions are answered. Greetings get a friendly reply; anything else is
            # politely redirected without creating a case, a feedback request or a review item.
            chat_reply = None if guided_category else small_talk_reply(complaint)
            if chat_reply or not is_telecom_question(complaint, taxonomy=taxonomy_service.get(db),
                                                     classification_method=analysis.classification_method,
                                                     used_memory=analysis.used_memory, guided_category=guided_category,
                                                     top_similarity=max((c["similarity"] for c in analysis.candidates),
                                                                        default=0.0)):
                if chat_reply:
                    kind, reply = "small_talk", chat_reply
                elif is_vague_problem(complaint):  # "it's not working": ask which service, don't say "sorry"
                    kind, reply = "clarify", CLARIFY_REPLY
                else:
                    kind, reply = "out_of_scope", OUT_OF_SCOPE_REPLY
                s.memory.add_message(db, session, "assistant", reply, {"type": kind})
                log_event("message_out_of_scope" if kind == "out_of_scope" else "small_talk", db=db,
                          session_id=session.id, complaint_preview=complaint[:80])
                db.commit()
                tracker.finish("success", {"out_of_scope": "not a telecom question", "clarify": "asked which service"}.get(kind, "greeting"))
                raise OutOfScope(reply, code={"out_of_scope": "OUT_OF_SCOPE", "clarify": "NEEDS_DETAILS"}.get(kind, "SMALL_TALK"),
                                 details={"reply": reply})
        except OutOfScope:
            raise
        except Exception as exc:
            tracker.fail(f"understanding failed: {exc.__class__.__name__}")
            raise
        tracker.finish("success", f"intent={analysis.intent} ({analysis.classification_method}), "
                                  f"severity={analysis.severity}, sentiment={analysis.sentiment}"
                                  + (", memory applied" if analysis.used_memory else ""))

        run = self._run(db, request_id=request_id, session=session, complaint=complaint, analysis=analysis,
                        effective_query=effective_query, guided_category=guided_category, attempt_number=1,
                        exclude_ids=set(), previous_steps=[], additional_info=None, tracker=tracker,
                        memory_context=memory_context, widen=False)
        mode = run["mode"]
        answer = run["answer"]
        case = SupportCase(
            id=short_id("CASE"), session_id=session.id, request_id=request_id, complaint=complaint,
            effective_query=effective_query, guided_category=guided_category, input_mode=input_mode,
            analysis=analysis.to_dict(), intent=analysis.intent, category=analysis.category, product=analysis.product,
            severity=analysis.severity, sentiment=analysis.sentiment, evidence_score=run["assessment"].score,
            evidence_status=mode, status="awaiting_feedback", current_attempt=1, escalated=answer.escalation,
            escalation_reason=answer.escalation_reason, used_memory=analysis.used_memory,
            embedding=run["qvec"], embedding_model=s.embeddings.model_id if run["qvec"] is not None else None,
        )
        db.add(case)
        db.flush()
        tracker.start("complete")
        total_ms = (time.perf_counter() - started) * 1000
        tracker.finish("success", f"case {case.id} stored ({total_ms:.0f} ms)")
        case.latency_ms = round(total_ms, 2)
        attempt = self._persist_attempt(db, case, 1, run, effective_query, None, set(), tracker, total_ms)
        s.memory.update_after_resolution(session, analysis, complaint, case.id, 1, mode, answer.summary)
        s.memory.add_message(db, session, "assistant", assistant_reply(answer, 1), {"case_id": case.id, "attempt": 1, "status": mode,
                                                                 "evidence_score": round(run["assessment"].score, 4)})
        memory_context = s.memory.load(db, session)
        self._log(db, "resolution_completed", request_id, case, run, total_ms, attempt=1)
        if analysis.severity == "critical":
            handoff.request_agent(db, session.id, f"Critical issue ({analysis.intent_display}) on {case.id}",
                                  by="system", case_id=case.id)
        if mode == "unknown":
            self._detect_emerging(db)
        db.commit()
        return self._response(request_id=request_id, case=case, attempt=attempt, analysis=analysis.to_dict(), run=run,
                              tracker=tracker, memory_context=memory_context, session=session, total_ms=total_ms)

    # ================================================================ retry
    def retry(self, db: Session, *, case_id: str, additional_info: str | None, on_stage: StageCallback | None = None) -> dict:
        request_id = request_id_var.get() or new_request_id()
        started = time.perf_counter()
        s = self.s
        settings = self.settings
        case = db.get(SupportCase, case_id)
        if case is None:
            raise NotFoundError(f"Case {case_id} not found")
        if case.status not in ("retry_pending", "needs_more_info"):
            raise ConflictError(f"Case {case_id} cannot be retried while its status is '{case.status}' (record NO or PARTIAL feedback first)",
                                code="RETRY_NOT_ALLOWED")
        if case.current_attempt >= settings.max_resolution_attempts:
            raise ConflictError("Maximum resolution attempts reached; the case must be escalated",
                                code="MAX_ATTEMPTS_REACHED")
        tracker = StageTracker(on_stage)
        tracker.start("understanding")
        previous = db.scalars(select(ResolutionAttempt).where(ResolutionAttempt.case_id == case.id)
                              .order_by(ResolutionAttempt.attempt_number)).all()
        exclude_ids = {c["source_id"] for a in previous for c in (a.citations or [])}
        previous_steps = [st["text"] for a in previous for st in (a.steps or []) if st.get("kind") == "resolution"]
        session = s.memory.get_or_create(db, case.session_id)
        memory_context = s.memory.load(db, session)
        query = case.effective_query + (f" Additional information: {additional_info}" if additional_info else "")
        analysis = s.classifier.classify(db, f"{case.complaint} {additional_info or ''}".strip(), case.guided_category)
        if analysis.intent == "unknown" and case.intent != "unknown":
            stored = case.analysis or {}
            for key in ("intent", "intent_display", "intent_confidence", "category", "subcategory", "support_category",
                        "domain_category", "product"):
                if key in stored:
                    setattr(analysis, key, stored[key])
            analysis.classification_method = "previous_attempt"
        analysis.used_memory = True
        if additional_info:
            s.memory.add_message(db, session, "user", additional_info, {"case_id": case.id, "type": "additional_info"})
        tracker.finish("success", f"attempt {case.current_attempt + 1}: excluding {len(exclude_ids)} previously cited "
                                  f"source(s), widening filters")
        attempt_number = case.current_attempt + 1
        run = self._run(db, request_id=request_id, session=session, complaint=case.complaint, analysis=analysis,
                        effective_query=query, guided_category=case.guided_category, attempt_number=attempt_number,
                        exclude_ids=exclude_ids, previous_steps=previous_steps, additional_info=additional_info,
                        tracker=tracker, memory_context=memory_context, widen=True)
        tracker.start("complete")
        total_ms = (time.perf_counter() - started) * 1000
        tracker.finish("success", f"attempt {attempt_number} stored")
        attempt = self._persist_attempt(db, case, attempt_number, run, query, additional_info, exclude_ids, tracker, total_ms)
        case.current_attempt = attempt_number
        case.evidence_score = run["assessment"].score
        case.evidence_status = run["mode"]
        case.status = "awaiting_feedback"
        case.escalated = case.escalated or run["answer"].escalation
        case.escalation_reason = run["answer"].escalation_reason or case.escalation_reason
        case.analysis = {**(case.analysis or {}), "intent": analysis.intent, "intent_display": analysis.intent_display}
        case.intent = analysis.intent
        case.updated_at = utcnow()
        s.memory.update_after_resolution(session, analysis, case.complaint, case.id, attempt_number, run["mode"], run["answer"].summary)
        s.memory.add_message(db, session, "assistant", assistant_reply(run["answer"], attempt_number),
                             {"case_id": case.id, "attempt": attempt_number, "status": run["mode"]})
        memory_context = s.memory.load(db, session)
        self._log(db, "resolution_retry", request_id, case, run, total_ms, attempt=attempt_number)
        db.commit()
        return self._response(request_id=request_id, case=case, attempt=attempt, analysis=analysis.to_dict(), run=run,
                              tracker=tracker, memory_context=memory_context, session=session, total_ms=total_ms)

    # ============================================================= feedback
    def feedback(self, db: Session, *, case_id: str, outcome: str, attempt_number: int | None, comment: str | None) -> dict:
        settings = self.settings
        case = db.get(SupportCase, case_id)
        if case is None:
            raise NotFoundError(f"Case {case_id} not found")
        number = attempt_number or case.current_attempt
        attempt = db.scalar(select(ResolutionAttempt).where(ResolutionAttempt.case_id == case.id,
                                                            ResolutionAttempt.attempt_number == number))
        if attempt is None:
            raise NotFoundError(f"Attempt {number} not found for case {case_id}")
        if number != case.current_attempt:
            raise ConflictError("Feedback can only be given for the latest attempt", code="STALE_ATTEMPT")
        if db.scalar(select(Feedback).where(Feedback.case_id == case.id, Feedback.attempt_number == number)):
            raise ConflictError(f"Feedback for attempt {number} was already recorded", code="FEEDBACK_EXISTS")
        if case.status in ("resolved", "candidate_submitted", "escalated"):
            raise ConflictError(f"Case is already {case.status}", code="CASE_CLOSED")

        fb = Feedback(case_id=case.id, attempt_id=attempt.id, attempt_number=number, outcome=outcome, comment=comment,
                      answer_snapshot={"summary": attempt.summary, "steps": attempt.steps, "status": attempt.status},
                      retrieved_source_ids=[x["source_id"] for x in attempt.sources])
        db.add(fb)
        db.flush()
        remaining = max(0, settings.max_resolution_attempts - case.current_attempt)
        candidate_id = None
        if outcome == "solved":
            if attempt.status == "known" and is_dataset_query(db, case.complaint):
                case.status, action = "resolved", "closed"
                message = "Marked as solved using verified knowledge. No new knowledge is needed."
            elif attempt.status == "known":
                # Verified answer, but the customer's wording is new: a reviewer decides whether it joins the dataset.
                candidate = self.s.knowledge.create_candidate_from_case(db, case, attempt, outcome, origin="kb_match")
                candidate_id = candidate.id
                case.status, action = "candidate_submitted", "candidate_created"
                message = ("Marked as solved using verified knowledge. This was a new customer query, so it was sent for "
                           "human review before being added to the dataset.")
            else:
                candidate = self.s.knowledge.create_candidate_from_case(db, case, attempt, outcome)
                candidate_id = candidate.id
                case.status, action = "candidate_submitted", "candidate_created"
                message = ("Customer confirmed the candidate resolution. It was saved as CANDIDATE knowledge and now "
                           "needs human verification before it can become trusted knowledge.")
        elif remaining == 0:
            case.status, action = "escalated", "escalated"
            case.escalated = True
            case.escalation_reason = (f"Maximum resolution attempts ({settings.max_resolution_attempts}) reached without "
                                      f"a confirmed fix. Escalated to a human agent.")
            message = case.escalation_reason
            handoff.request_agent(db, case.session_id, f"{case.id}: maximum resolution attempts reached",
                                  by="system", case_id=case.id)
        elif outcome == "partially_solved":
            case.status, action = "needs_more_info", "provide_more_info"
            message = "Partially solved. Collect additional information from the customer, then run the next attempt."
        else:
            case.status, action = "retry_pending", "retry"
            message = "Not solved. The next attempt will retrieve alternative evidence and exclude sources already used."
        case.updated_at = utcnow()
        session = self.s.memory.get_or_create(db, case.session_id)
        self.s.memory.record_feedback(session, case.id, number, outcome, comment)
        self.s.memory.add_message(db, session, "system", f"Feedback on attempt {number}: {outcome.replace('_', ' ')}. {message}",
                                  {"case_id": case.id, "attempt": number, "feedback": outcome, "next_action": action})
        log_event("feedback_recorded", db=db, session_id=case.session_id, case_id=case.id, attempt=number,
                  feedback=outcome, outcome=action)
        db.commit()
        return {"feedback_id": fb.id, "case_id": case.id, "attempt_number": number, "outcome": outcome,
                "next_action": action, "message": message, "candidate_id": candidate_id, "case_status": case.status,
                "attempts_remaining": max(0, settings.max_resolution_attempts - case.current_attempt)}

    # ================================================================ reads
    def get_case(self, db: Session, case_id: str) -> dict:
        case = db.get(SupportCase, case_id)
        if case is None:
            raise NotFoundError(f"Case {case_id} not found")
        attempts = db.scalars(select(ResolutionAttempt).where(ResolutionAttempt.case_id == case_id)
                              .order_by(ResolutionAttempt.attempt_number)).all()
        feedback = db.scalars(select(Feedback).where(Feedback.case_id == case_id).order_by(Feedback.id)).all()
        candidates = db.scalars(select(CandidateCase).where(CandidateCase.case_id == case_id)).all()
        data = case_summary(case)
        data.update({
            "request_id": case.request_id, "effective_query": case.effective_query, "guided_category": case.guided_category,
            "analysis": case.analysis, "escalation_reason": case.escalation_reason, "used_memory": case.used_memory,
            "max_attempts": self.settings.max_resolution_attempts,
            "attempts": [attempt_to_dict(a) for a in attempts],
            "feedback": [{"id": f.id, "attempt_number": f.attempt_number, "outcome": f.outcome, "comment": f.comment,
                          "retrieved_source_ids": f.retrieved_source_ids,
                          "created_at": f.created_at.isoformat() if f.created_at else None} for f in feedback],
            "candidates": [{"id": c.id, "status": c.status, "approved_article_id": c.approved_article_id} for c in candidates],
        })
        return data

    def list_cases(self, db: Session, *, status: str | None, evidence_status: str | None, session_id: str | None,
                   limit: int, offset: int) -> dict:
        stmt = select(SupportCase)
        if status:
            stmt = stmt.where(SupportCase.status == status)
        if evidence_status:
            stmt = stmt.where(SupportCase.evidence_status == evidence_status)
        if session_id:
            stmt = stmt.where(SupportCase.session_id == session_id)
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.scalars(stmt.order_by(SupportCase.created_at.desc()).offset(offset).limit(limit)).all()
        return {"items": [case_summary(c) for c in rows], "total": total}

    # =============================================================== logging
    def _log(self, db: Session, event: str, request_id: str, case: SupportCase, run: dict, total_ms: float, attempt: int) -> None:
        sources = run["sources"][:5]
        log_event(
            event, db=db, request_id=request_id, session_id=case.session_id, case_id=case.id, intent=case.intent,
            attempt=attempt, evidence_score=round(run["assessment"].score, 4), outcome=run["mode"],
            retrieval_scores=[round(x.hybrid_score, 4) for x in sources],
            reranker_scores=[round(x.reranker_score, 4) if x.reranker_score is not None else None for x in sources],
            retrieval_latency_ms=round(run["outcome"].latency_ms, 2), llm_latency_ms=run["answer"].llm_latency_ms,
            total_latency_ms=round(total_ms, 2), num_sources=len(run["sources"]), generator=run["answer"].generator,
            complaint_preview=truncate(case.complaint, 60),
        )
