"""EvidenceScoringService: decides KNOWN / UNCERTAIN / UNKNOWN.

evidence_score = w_sem * semantic_similarity + w_rr * reranker_score + w_int * intent_match
               + w_q * source_quality + w_meta * metadata_match

All weights and thresholds come from Settings (single source of truth).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.config import get_settings
from app.services.retrieval import ScoredSource
from app.services.taxonomy import TaxonomySnapshot


@dataclass
class EvidenceAssessment:
    score: float
    status: str  # known | uncertain | unknown
    components: dict
    top_similarity: float
    intent_match: float
    relevant_sources: int
    reasons: list[str] = field(default_factory=list)
    thresholds: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["score"] = round(self.score, 4)
        data["top_similarity"] = round(self.top_similarity, 4)
        data["components"] = {k: round(v, 4) for k, v in self.components.items()}
        return data


class EvidenceScoringService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def intent_match(self, query_intent: str | None, source: ScoredSource, taxonomy: TaxonomySnapshot) -> float:
        if not query_intent or query_intent == "unknown":
            return 0.5  # cannot confirm or contradict
        if source.intent == query_intent:
            return 1.0
        q = taxonomy.intents.get(query_intent)
        if q and taxonomy.top_category(q.support_category) == taxonomy.top_category(source.category):
            return 0.25  # related but different intent: partial, weaker than "cannot tell"
        return 0.0

    def score(self, sources: list[ScoredSource], query_intent: str | None, taxonomy: TaxonomySnapshot) -> EvidenceAssessment:
        s = self.settings
        thresholds = {"known": s.known_threshold, "unknown": s.unknown_threshold}
        # Evidence measures issue-specific verified knowledge: general checklists may guide a
        # candidate answer but never make an issue look known.
        sources = [x for x in sources if not (x.extra or {}).get("general")]
        if not sources:
            return EvidenceAssessment(0.0, "unknown", {"semantic": 0.0, "reranker": 0.0, "intent_match": 0.0,
                                                      "source_quality": 0.0, "metadata": 0.0}, 0.0, 0.0, 0,
                                      ["No evidence retrieved"], thresholds)
        top = sources[0]
        relevant = [x for x in sources if x.final_score >= s.min_relevant_score]
        semantic = top.semantic_score
        reranker = top.reranker_score if top.reranker_score is not None else top.hybrid_score
        intent = self.intent_match(query_intent, top, taxonomy)
        pool = relevant[:3] or [top]
        coverage = min(1.0, len(relevant) / 2.0)
        quality = (sum(x.quality for x in pool) / len(pool)) * (0.5 + 0.5 * coverage)
        metadata = top.metadata_score
        components = {"semantic": semantic, "reranker": reranker, "intent_match": intent,
                      "source_quality": quality, "metadata": metadata}
        total = (s.evidence_semantic_weight * semantic + s.evidence_reranker_weight * reranker
                 + s.evidence_intent_weight * intent + s.evidence_source_quality_weight * quality
                 + s.evidence_metadata_weight * metadata)
        total = max(0.0, min(1.0, total))
        status = s.classify_evidence(total)
        reasons = [
            f"Top source {top.source_id} semantic similarity {semantic:.2f}",
            f"Reranker relevance {reranker:.2f}" + ("" if top.reranker_score is not None else " (hybrid fallback)"),
            f"Intent match {intent:.2f}",
            f"{len(relevant)} relevant source(s) above {s.min_relevant_score:.2f}",
        ]
        return EvidenceAssessment(total, status, components, semantic, intent, len(relevant), reasons, thresholds)
