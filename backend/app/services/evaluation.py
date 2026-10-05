"""Offline evaluation on the calibration / held-out splits (never indexed).

Classification: accuracy, macro precision / recall / F1
Retrieval:      Recall@K (hit rate), MRR, nDCG@K  (relevant = source of the gold intent)
RAG:            groundedness, citation correctness, citation completeness, answer relevance
Unknown detection: share of out-of-taxonomy complaints NOT answered as KNOWN
Realistic questions (data/eval_realistic_complaints.csv, customer-style wording labelled by hand):
                issue-type accuracy, correct article ranked first, correct article in the top 3 sources,
                customer wording quality (no agent jargon, past-tense notes or fragments), one-article answers
End-to-end (live cases): resolution success rate, escalation rate, average attempts, average response time
"""
from __future__ import annotations

import csv
import math
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DATA_DIR, get_settings
from app.models import DocumentChunk, EvaluationRun, Feedback, SupportCase, Ticket
from app.services.adaptive_resolution import AdaptiveResolutionService, Services
from app.services.wording import customer_wording_issues
from app.utils.errors import ValidationFailed
from app.utils.text import strip_synthetic_tag, token_overlap

MIN_RELIABLE_SAMPLE = 30  # below this, one wrong answer moves a percentage by 3+ points
WORDINGS = ("original", "short", "typos", "casual", "noise")
_NOISE = ("I'm at work and in a hurry.", "Sorry for the long message, I've been trying to fix this all day.",
          "Hi there, quick question.", "This is the third time I'm contacting you.", "Writing from my partner's phone.")
_FILLER = re.compile(r"\s*(The issue|This has|I would like|I need|Please help|It is affecting|It has been)[^.]*\.", re.I)


def wording_variants(text: str, rng: random.Random) -> dict[str, str]:
    """The same complaint as customers really write it: short, with typos, casual, or with unrelated noise.

    Seeded, so every evaluation run tests exactly the same messages.
    """
    first = (re.split(r"(?<=[.!?])\s+", text.strip()) or [text])[0].rstrip(".!? ")
    short = _FILLER.sub("", first).strip() or first
    words = text.split()
    candidates = [i for i, w in enumerate(words) if len(w.strip(".,!?")) >= 6]
    for i in rng.sample(candidates, min(2, len(candidates))):  # swap two neighbouring letters in 1-2 long words
        w = words[i]
        j = rng.randrange(1, len(w.strip(".,!?")) - 2)
        words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2:]
    casual = short.lower().replace("cannot", "cant").replace("can't", "cant")
    return {"short": short[0].lower() + short[1:], "typos": " ".join(words),
            "casual": f"hey {casual}... can u help", "noise": f"{rng.choice(_NOISE)} {text}"}


def wilson_lower(successes: int, total: int, z: float = 1.96) -> float | None:
    """95% lower confidence bound for a success rate: 8/8 correct gives about 0.68, not certainty."""
    if total <= 0:
        return None
    p = successes / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return round(max(0.0, (centre - margin) / (1 + z * z / total)), 4)


def _ci(successes: int, total: int) -> dict:
    return {"successes": successes, "total": total, "lower_95": wilson_lower(successes, total)}


def classification_metrics(y_true: list[str], y_pred: list[str]) -> dict:
    labels = sorted(set(y_true))
    per_class = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
                            "support": tp + fn}
    n = len(labels) or 1
    accuracy = sum(1 for t, p in zip(y_true, y_pred) if t == p) / (len(y_true) or 1)
    return {"accuracy": round(accuracy, 4),
            "precision_macro": round(sum(v["precision"] for v in per_class.values()) / n, 4),
            "recall_macro": round(sum(v["recall"] for v in per_class.values()) / n, 4),
            "f1_macro": round(sum(v["f1"] for v in per_class.values()) / n, 4),
            "per_class": per_class}


def ranking_metrics(relevance_lists: list[list[int]], total_relevant: list[int], k: int) -> dict:
    hits, rr, ndcg = 0, 0.0, 0.0
    for rels, total in zip(relevance_lists, total_relevant):
        top = rels[:k]
        if any(top):
            hits += 1
            rr += 1.0 / (top.index(1) + 1)
        dcg = sum(r / math.log2(i + 2) for i, r in enumerate(top))
        ideal = sum(1 / math.log2(i + 2) for i in range(min(k, total)))
        ndcg += dcg / ideal if ideal else 0.0
    n = len(relevance_lists) or 1
    return {f"recall_at_{k}": round(hits / n, 4), "mrr": round(rr / n, 4), f"ndcg_at_{k}": round(ndcg / n, 4)}


class EvaluationService:
    def __init__(self, services: Services):
        self.s = services
        self.settings = get_settings()

    def _sample(self, db: Session, split: str, limit: int, seed: int) -> list[Ticket]:
        rows = db.scalars(select(Ticket).where(Ticket.dataset_split == split)).all()
        if not rows:
            raise ValidationFailed(f"No tickets found for split '{split}'")
        by_intent: dict[str, dict[str, Ticket]] = defaultdict(dict)
        for row in rows:  # de-duplicate templated complaints per intent
            by_intent[row.intent].setdefault(strip_synthetic_tag(row.customer_complaint), row)
        rng = random.Random(seed)
        pools = {k: rng.sample(list(v.values()), len(v)) for k, v in sorted(by_intent.items())}
        sample: list[Ticket] = []
        while len(sample) < limit and any(pools.values()):
            for intent in list(pools):
                if pools[intent] and len(sample) < limit:
                    sample.append(pools[intent].pop())
        return sample

    def _answer(self, db: Session, text: str):
        """Answer exactly as the live pipeline does (same ranking, article choice and wording), without saving."""
        analysis, run = AdaptiveResolutionService(self.s).answer_only(db, text)
        qvec = run["qvec"] if run["qvec"] is not None else self.s.embeddings.embed_one(text)
        return analysis, run["sources"], run["assessment"], run["answer"], qvec

    def _realistic(self, db: Session, path: Path | None = None) -> dict | None:
        """Customer-style questions labelled with the right issue type and help articles."""
        path = path or Path(DATA_DIR / "eval_realistic_complaints.csv")
        if not path.exists():
            return None
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        intent_ok = first_ok = top3_ok = clean = single = answered = 0
        issue_counts: Counter = Counter()
        failures: list[dict] = []
        for row in rows:
            expected = set(row["expected_articles"].split("|"))
            analysis, sources, _, answer, _ = self._answer(db, row["complaint"])
            resolution = [st for st in answer.steps if st["kind"] == "resolution"]
            cited = [c for st in resolution for c in st["citations"] if c.startswith("KB-")]
            first_article = cited[0] if cited else None
            top3 = [x.source_id for x in sources if x.source_type == "knowledge_base"][:3]
            problems = Counter(issue for st in answer.steps for issue in customer_wording_issues(
                st.get("customer_text") or "") if st.get("customer_text"))
            intent_ok += analysis.intent == row["expected_intent"]
            first_ok += first_article in expected
            top3_ok += bool(expected & set(top3))
            answered += bool(resolution)
            clean += not problems
            single += len({c for c in cited}) <= 1 or all(first_article in st["citations"] for st in resolution)
            issue_counts.update(problems)
            if analysis.intent != row["expected_intent"] or first_article not in expected or problems:
                failures.append({"complaint": row["complaint"], "expected_intent": row["expected_intent"],
                                 "got_intent": analysis.intent, "expected_articles": sorted(expected),
                                 "answered_from": first_article, "wording_issues": sorted(problems)})
        n = len(rows) or 1
        confidence = {"intent_accuracy": _ci(intent_ok, len(rows)), "correct_article_first": _ci(first_ok, len(rows)),
                      "correct_article_in_top3": _ci(top3_ok, len(rows)), "answered_with_steps": _ci(answered, len(rows)),
                      "clean_customer_wording": _ci(clean, len(rows)), "single_article_answers": _ci(single, len(rows))}
        return {"questions": len(rows), "confidence": confidence, "intent_accuracy": round(intent_ok / n, 4),
                "correct_article_first": round(first_ok / n, 4), "correct_article_in_top3": round(top3_ok / n, 4),
                "answered_with_steps": round(answered / n, 4), "clean_customer_wording": round(clean / n, 4),
                "single_article_answers": round(single / n, 4), "wording_issues": dict(issue_counts),
                "failures": failures[:20]}

    def run(self, db: Session, split: str = "held_out_test", limit: int = 120, seed: int = 7) -> dict:
        if split not in ("calibration", "held_out_test"):
            raise ValidationFailed("Evaluation split must be 'calibration' or 'held_out_test'")
        started = time.perf_counter()
        s = self.s
        k = self.settings.top_k
        s.retrieval.ensure_index(db)
        sample = self._sample(db, split, limit, seed)
        sample_ids = {t.ticket_id for t in sample}
        leaked = db.scalar(select(func.count()).select_from(DocumentChunk).where(
            DocumentChunk.source_type == "historical_ticket", DocumentChunk.source_id.in_(sample_ids))) or 0
        intent_doc_counts = dict(db.execute(select(DocumentChunk.intent, func.count(func.distinct(DocumentChunk.source_id)))
                                            .where(DocumentChunk.is_active.is_(True)).group_by(DocumentChunk.intent)).all())

        y_true, y_pred, rel_lists, totals = [], [], [], []
        grounded = steps_total = cited_steps = 0
        correct_citations = total_citations = 0
        relevance_scores: list[float] = []
        statuses: Counter = Counter()
        rng = random.Random(seed)
        by_wording = {w: [0, 0] for w in WORDINGS}
        rank1 = perfect_rankings = 0
        tested = [(ticket, wording, message) for ticket in sample
                  for wording, message in {"original": strip_synthetic_tag(ticket.customer_complaint),
                                           **wording_variants(strip_synthetic_tag(ticket.customer_complaint), rng)}.items()]
        for ticket, wording, text in tested:
            analysis, sources, assessment, answer, qvec = self._answer(db, text)
            by_wording[wording][0] += analysis.intent == ticket.intent
            by_wording[wording][1] += 1
            top = [1 if x.intent == ticket.intent else 0 for x in sources[:k]]
            rank1 += bool(top and top[0])
            ideal = min(k, intent_doc_counts.get(ticket.intent, 0))
            perfect_rankings += ideal > 0 and top[:ideal] == [1] * ideal  # every relevant source ranked first
            y_true.append(ticket.intent)
            y_pred.append(analysis.intent)
            statuses[assessment.status] += 1
            rel_lists.append([1 if x.intent == ticket.intent else 0 for x in sources[:k]])
            totals.append(intent_doc_counts.get(ticket.intent, 0))
            by_id = {x.source_id: x for x in sources}
            for step in answer.steps:
                if step["kind"] != "resolution":
                    continue
                steps_total += 1
                if step["citations"]:
                    cited_steps += 1
                    support = max(token_overlap(step["text"], by_id[c].content) for c in step["citations"] if c in by_id)
                    grounded += 1 if support >= 0.5 else 0
            for cit in answer.citations:
                total_citations += 1
                src = by_id.get(cit["source_id"])
                correct_citations += 1 if src is not None and src.intent == ticket.intent else 0
            answer_text = " ".join([answer.summary] + [st["text"] for st in answer.steps])
            relevance_scores.append(float(np.dot(qvec, s.embeddings.embed_one(answer_text))))

        unknown_path = Path(DATA_DIR / "eval_unknown_complaints.csv")
        unknown_total = unknown_flagged = 0
        if unknown_path.exists():
            with unknown_path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    _, _, assessment, _, _ = self._answer(db, row["complaint"])
                    unknown_total += 1
                    unknown_flagged += 1 if assessment.status != "known" else 0

        realistic = self._realistic(db)
        correct = sum(1 for t, p_ in zip(y_true, y_pred) if t == p_)
        predicted = sum(1 for p_ in y_pred if p_ != "unknown")
        hits = sum(1 for rels in rel_lists if any(rels[:k]))
        confidence = {
            "accuracy": _ci(correct, len(y_true)), "precision_macro": _ci(correct, predicted),
            "recall_macro": _ci(correct, len(y_true)), f"recall_at_{k}": _ci(hits, len(rel_lists)),
            "mrr": _ci(rank1, len(rel_lists)), f"ndcg_at_{k}": _ci(perfect_rankings, len(rel_lists)),
            "groundedness": _ci(grounded, steps_total), "citation_correctness": _ci(correct_citations, total_citations),
            "citation_completeness": _ci(cited_steps, steps_total), "unknown_detection": _ci(unknown_flagged, unknown_total),
        }
        p_low, r_low = confidence["precision_macro"]["lower_95"], confidence["recall_macro"]["lower_95"]
        # F1 is a harmonic mean, so it is never below the smaller of precision and recall.
        confidence["f1_macro"] = {"lower_95": min(p_low, r_low) if p_low is not None and r_low is not None else None}

        cases_total = db.scalar(select(func.count()).select_from(SupportCase)) or 0
        fb_total = db.scalar(select(func.count()).select_from(Feedback)) or 0
        fb_solved = db.scalar(select(func.count()).select_from(Feedback).where(Feedback.outcome == "solved")) or 0
        escalated = db.scalar(select(func.count()).select_from(SupportCase).where(SupportCase.status == "escalated")) or 0
        avg_attempts = db.scalar(select(func.avg(SupportCase.current_attempt))) or 0.0
        avg_latency = db.scalar(select(func.avg(SupportCase.latency_ms))) or 0.0

        metrics = {
            "classification": classification_metrics(y_true, y_pred),
            "retrieval": ranking_metrics(rel_lists, totals, k),
            "rag": {
                "groundedness": round(grounded / steps_total, 4) if steps_total else None,
                "citation_correctness": round(correct_citations / total_citations, 4) if total_citations else None,
                "citation_completeness": round(cited_steps / steps_total, 4) if steps_total else None,
                "answer_relevance": round(float(np.mean(relevance_scores)), 4) if relevance_scores else None,
            },
            "evidence_status_distribution": dict(statuses),
            "unknown_detection": {"out_of_taxonomy_samples": unknown_total,
                                  "flagged_not_known": unknown_flagged,
                                  "detection_rate": round(unknown_flagged / unknown_total, 4) if unknown_total else None},
            "end_to_end": {"cases": cases_total, "resolution_success_rate": round(fb_solved / fb_total, 4) if fb_total else None,
                           "escalation_rate": round(escalated / cases_total, 4) if cases_total else None,
                           "average_attempts": round(float(avg_attempts), 3), "average_response_ms": round(float(avg_latency), 1)},
            "realistic": realistic,
            "sample": {"unique_complaints": len(sample), "wordings": len(WORDINGS), "tested": len(tested)},
            "by_wording": {w: {"correct": c, "total": t, "accuracy": round(c / t, 4) if t else None,
                               "lower_95": wilson_lower(c, t)} for w, (c, t) in by_wording.items()},
            "confidence": confidence,
            # Groundedness only measures something when an LLM writes the steps; templates copy them from sources.
            "generator": "llm" if s.rag.provider.is_llm else "template",
            "leakage_check": {"evaluated_tickets_found_in_index": leaked},
            "intents_in_sample": sorted(set(y_true)),
        }
        warnings = []
        if len(sample) < MIN_RELIABLE_SAMPLE:
            warnings.append(f"Only {len(sample)} distinct complaints in the {split} split (the synthetic tickets repeat a "
                            f"few templates); each is also tested in {len(WORDINGS) - 1} realistic rewordings. Scores are "
                            f"shown with their 95% lower bound, since a perfect score on a small sample is not proof of "
                            f"perfection. The realistic customer questions give a more reliable picture.")
        if not s.rag.provider.is_llm:
            warnings.append("Demo mode: answers are copied from their sources, so groundedness is not measured. "
                            "It becomes a real measurement with the LLM (AI mode) on, where steps can drift from sources.")
        metrics["warnings"] = warnings
        duration = (time.perf_counter() - started) * 1000
        run = EvaluationRun(split=split, sample_size=len(sample), status="completed", metrics=metrics,
                            config={"top_k": k, "known_threshold": self.settings.known_threshold,
                                    "unknown_threshold": self.settings.unknown_threshold,
                                    "embedding": s.embeddings.model_id, "reranker": s.reranker.status()["loaded"],
                                    "weights": {"semantic": self.settings.semantic_weight, "keyword": self.settings.keyword_weight,
                                                "metadata": self.settings.metadata_weight}, "seed": seed},
                            notes="Synthetic dataset; split is intent-disjoint, so held-out intents are unseen in ticket history.",
                            duration_ms=round(duration, 1))
        db.add(run)
        db.commit()
        return run_to_dict(run)


def run_to_dict(run: EvaluationRun) -> dict:
    return {"id": run.id, "split": run.split, "sample_size": run.sample_size, "status": run.status, "metrics": run.metrics,
            "config": run.config, "notes": run.notes, "duration_ms": run.duration_ms,
            "created_at": run.created_at.isoformat() if run.created_at else None}
