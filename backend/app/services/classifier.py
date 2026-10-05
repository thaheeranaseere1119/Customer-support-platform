"""ClassificationService: complaint understanding.

Order of strategies:
1. LLM classification constrained to the DB taxonomy (AI mode only, validated).
2. Deterministic keyword rules loaded from the `intent_taxonomy` table.
3. Embedding similarity against each intent's example complaints (so admin-created
   intents become classifiable immediately).
4. Otherwise `unknown` - classification is never forced.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass, field

import numpy as np
from sqlalchemy.orm import Session

from app.services.embeddings import EmbeddingService
from app.services.entity_extractor import extract_entities
from app.services.llm_provider import LLMProvider
from app.services.sentiment import analyze_sentiment, estimate_severity
from app.services.taxonomy import TaxonomySnapshot, taxonomy_service
from app.utils.text import contains_phrase, tokenize

logger = logging.getLogger(__name__)


@dataclass
class Analysis:
    intent: str
    intent_display: str
    intent_confidence: float
    classification_method: str
    category: str
    subcategory: str | None
    support_category: str
    domain_category: str
    product: str
    severity: str
    severity_reasons: list[str]
    sentiment: str
    sentiment_score: float
    entities: list[dict]
    candidates: list[dict] = field(default_factory=list)
    memory_entities: list[dict] = field(default_factory=list)
    used_memory: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class ClassificationService:
    def __init__(self, embeddings: EmbeddingService, llm: LLMProvider):
        self.embeddings = embeddings
        self.llm = llm
        self._example_cache: tuple[tuple, list[str], np.ndarray] | None = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- helpers
    def _rule_scores(self, text: str, taxonomy: TaxonomySnapshot) -> dict[str, float]:
        tokens = tokenize(text)
        scores: dict[str, float] = {}
        for intent in taxonomy.intents.values():
            score = 0.0
            for phrase in intent.keywords:
                ptoks = tokenize(phrase)
                if ptoks and contains_phrase(tokens, ptoks):
                    score += len(ptoks)
            if score:
                scores[intent.name] = score
        return scores

    def _example_matrix(self, taxonomy: TaxonomySnapshot) -> tuple[list[str], np.ndarray]:
        key = (taxonomy.version, self.embeddings.model_id)
        if self._example_cache and self._example_cache[0] == key:
            return self._example_cache[1], self._example_cache[2]
        with self._lock:
            labels, texts = [], []
            for intent in taxonomy.intents.values():
                for example in (*intent.examples, f"{intent.display_name}. {intent.description}"):
                    labels.append(intent.name)
                    texts.append(example)
            matrix = self.embeddings.embed(texts) if texts else np.zeros((0, self.embeddings.dim), np.float32)
            self._example_cache = (key, labels, matrix)
            return labels, matrix

    def _embedding_scores(self, text: str, taxonomy: TaxonomySnapshot) -> dict[str, float]:
        try:
            labels, matrix = self._example_matrix(taxonomy)
            if not labels:
                return {}
            sims = matrix @ self.embeddings.embed_one(text)
        except Exception as exc:
            logger.warning("Embedding-based classification unavailable: %s", exc.__class__.__name__)
            return {}
        best: dict[str, float] = {}
        for label, sim in zip(labels, sims.tolist()):
            best[label] = max(best.get(label, -1.0), float(sim))
        return best

    def detect_product(self, text: str, taxonomy: TaxonomySnapshot, intent: str | None) -> str:
        tokens = tokenize(text, keep_stopwords=True)
        best, best_len = None, 0
        intent_cat = taxonomy.top_category(taxonomy.intents[intent].support_category) if intent in taxonomy.intents else None
        for name, category, keyword_tokens in taxonomy.products:
            for ktoks in keyword_tokens:
                if ktoks and contains_phrase(tokens, ktoks):
                    length = len(ktoks) + (0.5 if intent_cat and taxonomy.top_category(category) == intent_cat else 0)
                    if length > best_len:
                        best, best_len = name, length
        if intent in taxonomy.intents:
            default = taxonomy.intents[intent].default_product
            if best is None or (intent_cat and taxonomy.top_category(next((c for n, c, _ in taxonomy.products if n == best), "")) != intent_cat):
                return default or best or "unknown"
        return best or "unknown"

    def _llm_classify(self, text: str, taxonomy: TaxonomySnapshot) -> tuple[str, float] | None:
        if not self.llm.is_llm:
            return None
        catalogue = "\n".join(f"- {i.name}: {i.description}" for i in taxonomy.intents.values())
        system = ("You classify telecom support complaints. Choose exactly one intent name from the supplied list, "
                  "or 'unknown' if none fits. Do not invent new intent names. Return JSON {\"intent\": str, \"confidence\": float}.")
        user = f"Intents:\n{catalogue}\n\nComplaint:\n{text}"
        try:
            result = self.llm.complete_json("classify", system, user, payload={})
            intent = str(result.get("intent", "unknown")).strip()
            confidence = float(result.get("confidence", 0.0))
        except Exception as exc:
            logger.warning("LLM classification failed, using rules: %s", exc.__class__.__name__)
            return None
        if intent == "unknown" or intent in taxonomy.intents:
            return intent, max(0.0, min(1.0, confidence))
        logger.warning("LLM returned an intent outside the taxonomy; ignored")
        return None

    # ------------------------------------------------------------------- main
    def classify(self, db: Session, text: str, guided_category: str | None = None) -> Analysis:
        taxonomy = taxonomy_service.get(db)
        rules = self._rule_scores(text, taxonomy)
        if guided_category:
            allowed = taxonomy.categories_under(guided_category)
            for name in list(rules):
                if taxonomy.intents[name].support_category in allowed:
                    rules[name] += 0.5
        embedding = self._embedding_scores(text, taxonomy)
        threshold = self.embeddings.intent_example_threshold()

        intent, confidence, method = "unknown", 0.0, "none"
        llm_result = self._llm_classify(text, taxonomy)
        if llm_result is not None:
            intent, confidence = llm_result
            method = "llm"
        if method == "none" and rules:
            rule_intent, rule_score = max(rules.items(), key=lambda kv: (kv[1], embedding.get(kv[0], 0.0)))
            emb_intent, emb_score = max(embedding.items(), key=lambda kv: kv[1]) if embedding else (None, 0.0)
            if rule_score <= 1.5 and emb_intent and emb_intent != rule_intent and emb_score >= threshold + 0.08:
                intent, confidence, method = emb_intent, min(0.9, emb_score), "embedding_override"
            else:
                agree = 0.1 if embedding.get(rule_intent, 0.0) >= threshold else 0.0
                intent, confidence, method = rule_intent, min(0.97, 0.55 + 0.1 * rule_score + agree), "keyword_rules"
        if method == "none" and embedding:
            emb_intent, emb_score = max(embedding.items(), key=lambda kv: kv[1])
            if emb_score >= threshold:
                intent, confidence, method = emb_intent, min(0.9, emb_score), "embedding_examples"

        candidates = sorted(
            ({"intent": n, "rule_score": rules.get(n, 0.0), "similarity": round(embedding.get(n, 0.0), 4)}
             for n in set(rules) | set(sorted(embedding, key=lambda k: -embedding[k])[:3])),
            key=lambda c: (-c["rule_score"], -c["similarity"]),
        )[:5]

        info = taxonomy.intents.get(intent)
        product = self.detect_product(text, taxonomy, intent if info else None)
        if info:
            support_category = info.support_category
            domain = info.domain_category
            display = info.display_name
        else:
            product_cat = next((c for n, c, _ in taxonomy.products if n == product), None)
            support_category = guided_category or product_cat or "Unclassified"
            domain = "UNKNOWN"
            display = "Unknown / New Issue"
            confidence = 0.0
            method = method if method == "llm" else "no_match"
        sentiment = analyze_sentiment(text)
        severity = estimate_severity(text, sentiment, intent, domain)
        return Analysis(
            intent=intent, intent_display=display, intent_confidence=round(confidence, 3), classification_method=method,
            category=taxonomy.top_category(support_category), subcategory=taxonomy.subcategory(support_category),
            support_category=support_category, domain_category=domain, product=product, severity=severity.label,
            severity_reasons=severity.reasons, sentiment=sentiment.label, sentiment_score=sentiment.score,
            entities=[e.to_dict() for e in extract_entities(text)], candidates=candidates,
        )
