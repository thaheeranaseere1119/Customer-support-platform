"""Evidence-aware RAG generation with an anti-hallucination grounding guard.

Whatever generates the draft (Gemini in AI mode, the deterministic MockProvider in
demo mode) the output is validated here:
* citations must reference a supplied source ID (fake citations are removed);
* resolution steps without a valid citation, or whose wording is not supported by
  the cited source, are dropped;
* money / percentage / time-limit figures that do not appear in the cited evidence
  are rejected (no invented prices, refunds or guarantees);
* if nothing grounded survives, the answer is downgraded to "insufficient evidence".
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field

from app.config import get_settings
from app.services import grounded_templates
from app.services.llm_provider import LLMProvider, get_fallback_provider
from app.services.retrieval import ScoredSource
from app.utils.text import token_overlap, truncate

logger = logging.getLogger(__name__)

GROUNDING_RULES = """Use only the supplied evidence.
Do not invent unsupported facts.
If the evidence is insufficient, say that the evidence is insufficient.
Do not create fake sources or citations.
Never invent telecom policies, pricing, refund rules, account information, network configuration, customer
information, technical guarantees, unsupported troubleshooting steps, company-specific procedures or unsupported causes.
Every recommended step must cite at least one supplied source ID in its "citations" list, e.g. ["KB-010"].
If the mode is "uncertain" or "unknown", clearly label the answer as a CANDIDATE that is not verified."""

SYSTEM_PROMPT = f"""You are an evidence-aware telecom support resolution assistant for human support agents.
{GROUNDING_RULES}
Respond with a JSON object only, using exactly these keys:
{{"summary": str, "diagnosis": str, "steps": [{{"text": str, "citations": [str]}}], "warnings": [str],
  "escalation": bool, "escalation_reason": str | null, "insufficient_evidence": bool}}"""

CITATION_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9_\-:.]{1,60})\]")
FIGURE_RE = re.compile(r"(?:[₹$£€]\s?\d[\d,.]*|\b\d+(?:\.\d+)?\s?(?:%|percent|rs\b|inr\b|usd\b|dollars?|rupees?|"
                       r"days?|hours?|business days|weeks?|mbps|gbps))", re.I)


def is_general(source: ScoredSource) -> bool:
    return bool((source.extra or {}).get("general"))


@dataclass
class RAGAnswer:
    summary: str
    diagnosis: str
    steps: list[dict]
    warnings: list[str]
    escalation: bool
    escalation_reason: str | None
    insufficient_evidence: bool
    citations: list[dict]
    generator: str
    llm_latency_ms: float
    follow_up_question: str | None = None
    guard_report: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class RAGService:
    def __init__(self, provider: LLMProvider):
        self.provider = provider
        self.fallback = get_fallback_provider()
        self.settings = get_settings()

    # ------------------------------------------------------------- selection
    def select_sources(self, mode: str, sources: list[ScoredSource], intent: str) -> list[ScoredSource]:
        s = self.settings
        if not sources:
            return []
        if mode == "known":
            top_intent = sources[0].intent
            chosen = [x for x in sources if x.final_score >= s.min_relevant_score and x.intent in {top_intent, intent}]
            return (chosen or sources[:1])[:4]
        # A candidate hypothesis needs reasonably similar AND relevant verified evidence.
        specific = [x for x in sources if not is_general(x) and x.semantic_score >= s.candidate_min_semantic
                    and (x.reranker_score is None or x.reranker_score >= s.candidate_min_reranker)][:3]
        if specific:
            return specific
        # Nothing issue-specific: fall back to the closest GENERAL checklist so the customer
        # still gets the best-suitable cited guidance (clearly labelled as general).
        general = [x for x in sources if is_general(x) and x.hybrid_score > 0]
        return general[:1]

    def build_prompt(self, payload: dict) -> str:
        lines = [f"Mode: {payload['mode']} (evidence score {payload['evidence']['score']:.2f}; KNOWN >= "
                 f"{payload['thresholds']['known']:.2f}, UNKNOWN < {payload['thresholds']['unknown']:.2f})",
                 f"Attempt: {payload['attempt']} of {payload['max_attempts']}",
                 f"Customer complaint: {payload['complaint']}",
                 f"Analysis: {json.dumps(payload['analysis'])}"]
        if payload.get("memory_summary"):
            lines.append(f"Conversation memory: {payload['memory_summary']}")
        if payload.get("troubleshooting"):
            lines.append("Already tried by customer: " + "; ".join(payload["troubleshooting"]))
        if payload.get("additional_info"):
            lines.append(f"Additional information from customer: {payload['additional_info']}")
        if payload.get("previous_steps"):
            lines.append("Steps already suggested in earlier attempts (do not repeat): " + " | ".join(payload["previous_steps"]))
        lines.append("Evidence (the ONLY facts you may use):")
        if not payload["sources"]:
            lines.append("(no sufficiently relevant evidence was retrieved)")
        for src in payload["sources"]:
            kind = "general checklist, not issue-specific" if src.get("general") else src["type"]
            lines.append(f"[{src['id']}] ({kind}) {src['title']}\n{truncate(src['content'], 1200)}")
        return "\n".join(lines)

    # ---------------------------------------------------------------- guard
    def guard(self, raw: dict, sources: list[ScoredSource], mode: str) -> tuple[dict, dict]:
        by_id = {s.source_id: s for s in sources}
        report = {"removed_steps": [], "removed_citations": [], "removed_figures": 0}

        def figures_ok(text: str, cited: list[str]) -> bool:
            evidence_text = " ".join(by_id[c].content.lower() for c in cited if c in by_id)
            return all(f.lower().strip() in evidence_text for f in FIGURE_RE.findall(text))

        def clean_inline(text: str) -> tuple[str, list[str]]:
            found = []

            def repl(match: re.Match) -> str:
                cid = match.group(1)
                if cid in by_id:
                    found.append(cid)
                    return match.group(0)
                report["removed_citations"].append(cid)
                return ""
            return re.sub(r"\s{2,}", " ", CITATION_RE.sub(repl, str(text or ""))).strip(), found

        steps: list[dict] = []
        for step in raw.get("steps") or []:
            if isinstance(step, str):
                step = {"text": step, "citations": []}
            text, inline = clean_inline(step.get("text", ""))
            text = CITATION_RE.sub("", text).strip()
            kind = step.get("kind", "resolution")
            requested = [str(c) for c in (step.get("citations") or [])] + inline
            valid = list(dict.fromkeys(c for c in requested if c in by_id))
            report["removed_citations"] += [c for c in requested if c not in by_id]
            if not text:
                continue
            if kind == "information_gathering":
                if FIGURE_RE.search(text):
                    report["removed_figures"] += 1
                    continue
                steps.append({"text": text, "citations": [], "kind": kind, "already_attempted": False})
                continue
            if not valid:
                report["removed_steps"].append({"text": text, "reason": "no valid citation"})
                continue
            support = max(token_overlap(text, by_id[c].content) for c in valid)
            if support < 0.3:
                report["removed_steps"].append({"text": text, "reason": f"not supported by cited source ({support:.2f})"})
                continue
            if not figures_ok(text, valid):
                report["removed_figures"] += 1
                report["removed_steps"].append({"text": text, "reason": "figure not present in evidence"})
                continue
            steps.append({"text": text, "citations": valid, "kind": "resolution",
                          "already_attempted": bool(step.get("already_attempted", False))})

        warnings = []
        for w in raw.get("warnings") or []:
            text, cited = clean_inline(w)
            if text and figures_ok(text, cited or list(by_id)):
                warnings.append(text)
        summary, _ = clean_inline(raw.get("summary", ""))
        diagnosis, _ = clean_inline(raw.get("diagnosis", ""))
        if not figures_ok(summary, list(by_id)):
            summary = "A grounded summary could not be produced because it contained figures that are not in the evidence."
            report["removed_figures"] += 1
        if not figures_ok(diagnosis, list(by_id)):
            diagnosis = "The evidence is insufficient to determine a cause."
            report["removed_figures"] += 1
        reason, _ = clean_inline(raw.get("escalation_reason") or "")
        insufficient = bool(raw.get("insufficient_evidence")) or not any(s["kind"] == "resolution" for s in steps)
        if insufficient and not steps:
            steps = [{"text": t, "citations": [], "kind": "information_gathering", "already_attempted": False}
                     for t in grounded_templates.INFO_GATHERING_STEPS]
        if insufficient and mode == "known":
            summary = "The evidence is insufficient: no grounded resolution steps could be verified against the sources."
        cleaned = {"summary": summary or "The evidence is insufficient.", "diagnosis": diagnosis or "The evidence is insufficient to determine a cause.",
                   "steps": steps, "warnings": warnings, "escalation": bool(raw.get("escalation")),
                   "escalation_reason": reason or None, "insufficient_evidence": insufficient}
        return cleaned, report

    # ------------------------------------------------------------- generate
    def generate(self, *, complaint: str, analysis: dict, mode: str, sources: list[ScoredSource], evidence: dict,
                 memory_summary: str, troubleshooting: list[str], customer_context: list[str], attempt: int,
                 previous_steps: list[str], additional_info: str | None, follow_up_question: str | None) -> RAGAnswer:
        s = self.settings
        payload = {
            "mode": mode, "complaint": complaint,
            "analysis": {k: analysis.get(k) for k in ("intent", "intent_display", "category", "product", "severity", "sentiment")},
            "evidence": evidence, "thresholds": {"known": s.known_threshold, "unknown": s.unknown_threshold},
            "sources": [{"id": x.source_id, "type": x.source_type, "title": x.title, "content": x.content,
                         "final_score": x.final_score, "semantic_score": x.semantic_score, "intent": x.intent,
                         "general": is_general(x)} for x in sources],
            "troubleshooting": troubleshooting, "customer_context": customer_context, "previous_steps": previous_steps,
            "attempt": attempt, "max_attempts": s.max_resolution_attempts, "additional_info": additional_info,
            "memory_summary": memory_summary,
        }
        started = time.perf_counter()
        generator = self.provider.name if self.provider.is_llm else "grounded_template"
        fallback_note = None
        try:
            raw = self.provider.complete_json("rag_answer", SYSTEM_PROMPT, self.build_prompt(payload), payload)
        except Exception as exc:
            logger.warning("LLM generation failed (%s); using deterministic grounded template", exc.__class__.__name__)
            raw = self.fallback.complete_json("rag_answer", SYSTEM_PROMPT, "", payload)
            generator = "grounded_template_fallback"
            fallback_note = "The LLM was unavailable, so a deterministic evidence-only template was used."
        latency = (time.perf_counter() - started) * 1000
        cleaned, report = self.guard(raw, sources, mode)
        if fallback_note:
            cleaned["warnings"].append(fallback_note)
        if self.provider.is_llm and generator == self.provider.name and not cleaned["steps"]:
            cleaned, report = self.guard(self.fallback.complete_json("rag_answer", SYSTEM_PROMPT, "", payload), sources, mode)
            generator = "grounded_template_fallback"

        cited_ids: list[str] = []
        for step in cleaned["steps"]:
            cited_ids += step["citations"]
        for text in [cleaned["summary"], cleaned["diagnosis"], cleaned["escalation_reason"] or "", *cleaned["warnings"]]:
            cited_ids += CITATION_RE.findall(text)
        by_id = {x.source_id: x for x in sources}
        citations = [{"source_id": cid, "source_type": by_id[cid].source_type, "title": by_id[cid].title,
                      "excerpt": by_id[cid].excerpt(), "score": round(by_id[cid].final_score, 4)}
                     for cid in dict.fromkeys(cited_ids) if cid in by_id]
        return RAGAnswer(summary=cleaned["summary"], diagnosis=cleaned["diagnosis"], steps=cleaned["steps"],
                         warnings=cleaned["warnings"], escalation=cleaned["escalation"],
                         escalation_reason=cleaned["escalation_reason"], insufficient_evidence=cleaned["insufficient_evidence"],
                         citations=citations, generator=generator, llm_latency_ms=round(latency, 2),
                         follow_up_question=follow_up_question, guard_report=report)
