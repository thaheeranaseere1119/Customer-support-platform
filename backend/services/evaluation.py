"""Offline evaluation on the calibration / held-out splits (never indexed).

Classification: accuracy, macro precision / recall / F1
Retrieval:      Recall@K (hit rate), MRR, nDCG@K  (relevant = source of the gold intent)
RAG:            groundedness, citation correctness, citation completeness, answer relevance
Unknown detection: share of out-of-taxonomy complaints NOT answered as KNOWN
End-to-end (live cases): resolution success rate, escalation rate, average attempts, average response time
"""
from __future__ import annotations

import csv
import math
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DATA_DIR, get_settings
from app.models import DocumentChunk, EvaluationRun, Feedback, SupportCase, Ticket
from app.services.adaptive_resolution import Services
from app.services.taxonomy import taxonomy_service
from app.utils.errors import ValidationFailed
from app.utils.text import strip_synthetic_tag, token_overlap


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
        s = self.s
        taxonomy = taxonomy_service.get(db)
        analysis = s.classifier.classify(db, text)
        qvec = s.embeddings.embed_one(text)
        outcome = s.retrieval.search(db, text, intent=analysis.intent, category=analysis.category,
                                     product=analysis.product, taxonomy=taxonomy, query_vector=qvec)
        sources, _ = s.reranker.rerank(text, outcome.sources)
        assessment = s.evidence.score(sources, analysis.intent, taxonomy)
        selected = s.rag.select_sources(assessment.status, sources, analysis.intent)
        answer = s.rag.generate(complaint=text, analysis=analysis.to_dict(), mode=assessment.status, sources=selected,
                                evidence={"score": assessment.score, "status": assessment.status,
                                          "top_similarity": assessment.top_similarity, "intent_match": assessment.intent_match},
                                memory_summary="", troubleshooting=[], customer_context=[], attempt=1, previous_steps=[],
                                additional_info=None, follow_up_question=None)
        return analysis, sources, assessment, answer, qvec

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
        for ticket in sample:
            text = strip_synthetic_tag(ticket.customer_complaint)
            analysis, sources, assessment, answer, qvec = self._answer(db, text)
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
            "leakage_check": {"evaluated_tickets_found_in_index": leaked},
            "intents_in_sample": sorted(set(y_true)),
        }
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
