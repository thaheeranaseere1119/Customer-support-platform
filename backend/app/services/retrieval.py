"""Hybrid retrieval: vector search + BM25 keyword search + metadata filtering/scoring.

hybrid_score = SEMANTIC_WEIGHT * semantic + KEYWORD_WEIGHT * keyword + METADATA_WEIGHT * metadata

* Vector search uses pgvector (SQL `<=>`) when available, otherwise an in-memory
  cosine-similarity matrix.
* If the embedding model fails at query time, retrieval degrades to keyword +
  metadata only (weights re-normalised) instead of failing.
* Only ACTIVE knowledge and trusted development-split tickets are ever indexed;
  held-out and calibration tickets are excluded at ingestion time.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import db_state
from app.models import DocumentChunk
from app.services.embeddings import EmbeddingService
from app.services.taxonomy import TaxonomySnapshot
from app.utils.text import stem_tokens, truncate

logger = logging.getLogger(__name__)


@dataclass
class IndexedDoc:
    chunk_id: str
    source_id: str
    source_type: str
    title: str
    content: str
    intent: str
    category: str
    domain_category: str
    product: str
    quality: float
    extra: dict


@dataclass
class ScoredSource:
    chunk_id: str
    source_id: str
    source_type: str
    title: str
    content: str
    intent: str
    category: str
    product: str
    quality: float
    extra: dict
    semantic_raw: float = 0.0
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    metadata_score: float = 0.0
    hybrid_score: float = 0.0
    reranker_score: float | None = None
    final_score: float = 0.0

    def excerpt(self, limit: int = 260) -> str:
        return truncate(self.content.replace("\n", " "), limit)

    def to_public(self) -> dict:
        data = asdict(self)
        data["excerpt"] = self.excerpt()
        for key in ("semantic_raw", "semantic_score", "keyword_score", "metadata_score", "hybrid_score", "final_score"):
            data[key] = round(float(data[key]), 4)
        if data["reranker_score"] is not None:
            data["reranker_score"] = round(float(data["reranker_score"]), 4)
        return data


@dataclass
class RetrievalFilters:
    guided_category: str | None = None
    exclude_source_ids: set[str] = field(default_factory=set)
    source_types: set[str] | None = None
    general_only: bool = False


@dataclass
class RetrievalOutcome:
    sources: list[ScoredSource]
    semantic_used: bool
    keyword_used: bool
    vector_backend: str
    filter_relaxed: bool
    degraded_reasons: list[str]
    latency_ms: float
    candidates_considered: int


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_len: list[int] = []
        self.avgdl = 0.0
        self.n = 0

    def build(self, texts: list[str]) -> None:
        self.postings.clear()
        self.doc_len = []
        for idx, txt in enumerate(texts):
            counts = Counter(stem_tokens(txt))
            self.doc_len.append(sum(counts.values()))
            for term, tf in counts.items():
                self.postings[term].append((idx, tf))
        self.n = len(texts)
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0

    def search(self, query: str) -> tuple[dict[int, float], dict[int, float]]:
        """Return (bm25 scores, query-term coverage) per doc index."""
        terms = list(dict.fromkeys(stem_tokens(query)))
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, int] = defaultdict(int)
        if not terms or not self.n:
            return {}, {}
        for term in terms:
            plist = self.postings.get(term)
            if not plist:
                continue
            df = len(plist)
            idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            for idx, tf in plist:
                dl = self.doc_len[idx]
                scores[idx] += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
                matched[idx] += 1
        coverage = {i: matched[i] / len(terms) for i in matched}
        return dict(scores), coverage


class RetrievalService:
    def __init__(self, embeddings: EmbeddingService):
        self.embeddings = embeddings
        self.settings = get_settings()
        self._docs: list[IndexedDoc] = []
        self._matrix: np.ndarray | None = None
        self._bm25 = BM25Index()
        self._dirty = True
        self._built_signature: tuple | None = None
        self._lock = threading.RLock()
        self.version = 0
        self.last_built_at: float | None = None

    # ---------------------------------------------------------------- indexing
    def mark_dirty(self) -> None:
        self._dirty = True

    @staticmethod
    def _signature(db: Session) -> tuple:
        """Changes whenever any process adds, edits or deactivates a chunk (separate workers or services)."""
        active = select(func.count()).select_from(DocumentChunk).where(DocumentChunk.is_active.is_(True))
        return (db.scalar(active), db.scalar(select(func.max(DocumentChunk.updated_at))))

    def ensure_index(self, db: Session) -> None:
        signature = self._signature(db)
        if not self._dirty and signature == self._built_signature:
            return
        with self._lock:
            if not self._dirty and signature == self._built_signature:
                return
            self._reembed_stale(db)
            rows = db.scalars(select(DocumentChunk).where(DocumentChunk.is_active.is_(True)).order_by(DocumentChunk.id)).all()
            docs, vectors = [], []
            for row in rows:
                docs.append(IndexedDoc(row.chunk_id, row.source_id, row.source_type, row.title, row.content, row.intent,
                                       row.category, row.domain_category, row.product, row.quality, row.extra or {}))
                vec = row.embedding
                vectors.append(vec if vec is not None and len(vec) == self.embeddings.dim else np.zeros(self.embeddings.dim, np.float32))
            self._docs = docs
            self._matrix = np.vstack(vectors).astype(np.float32) if vectors else np.zeros((0, self.embeddings.dim), np.float32)
            self._bm25.build([f"{d.title} {d.content}" for d in docs])
            self.version += 1
            self.last_built_at = time.time()
            self._dirty = False
            self._built_signature = self._signature(db)
            logger.info("Retrieval index built", extra={"fields": {"documents": len(docs), "index_version": self.version}})

    def _reembed_stale(self, db: Session) -> None:
        """Embed chunks that are missing vectors or were embedded by another model."""
        model_id = self.embeddings.model_id
        stale = db.scalars(select(DocumentChunk).where(DocumentChunk.is_active.is_(True)).where(
            (DocumentChunk.embedding_model.is_(None)) | (DocumentChunk.embedding_model != model_id))).all()
        if not stale:
            return
        batch = self.settings.embedding_batch_size * 4
        for start in range(0, len(stale), batch):
            part = stale[start:start + batch]
            vecs = self.embeddings.embed([f"{c.title}. {c.content}" for c in part])
            for chunk, vec in zip(part, vecs):
                chunk.embedding = vec
                chunk.embedding_model = model_id
        db.commit()
        logger.info("Re-embedded stale chunks", extra={"fields": {"count": len(stale), "model": model_id}})

    def stats(self) -> dict:
        by_type = Counter(d.source_type for d in self._docs)
        return {"documents": len(self._docs), "by_source_type": dict(by_type), "index_version": self.version,
                "vector_backend": "pgvector" if db_state.pgvector else "in_memory_cosine",
                "last_built_at": self.last_built_at}

    # ---------------------------------------------------------------- scoring
    @staticmethod
    def metadata_score(doc: IndexedDoc, intent: str | None, category: str | None, product: str | None,
                       taxonomy: TaxonomySnapshot) -> float:
        score = 0.0
        if intent and intent != "unknown" and doc.intent == intent:
            score += 0.5
        if category and category != "Unclassified" and taxonomy.top_category(doc.category) == category:
            score += 0.3
        if product and product != "unknown" and doc.product and doc.product.lower() == product.lower():
            score += 0.2
        return score

    def prefer_topic(self, sources: list[ScoredSource], category: str | None, taxonomy: TaxonomySnapshot, *,
                     strict: bool = False) -> list[ScoredSource]:
        """Rank sources from the question's topic above sources from other topics.

        The reranker scores word overlap, so a call-drop ticket can outrank the broadband article for "my internet
        keeps dropping". Off-topic sources keep `topic_mismatch_factor` of their score. With `strict` (the question
        itself names the topic), usable on-topic sources - those that would qualify for a candidate answer - are
        placed first. Nothing changes when no topic was detected or a source has no category.
        """
        if not category or category == "Unclassified":
            return sources
        s = self.settings

        def off_topic(src: ScoredSource) -> bool:
            own = taxonomy.top_category(src.category)
            return own != "Unclassified" and own != category

        def usable(src: ScoredSource) -> bool:
            return (src.semantic_score >= s.candidate_min_semantic
                    and (src.reranker_score is None or src.reranker_score >= s.candidate_min_reranker))

        for src in sources:
            if off_topic(src):
                src.final_score *= s.topic_mismatch_factor
        ranked = sorted(sources, key=lambda x: -x.final_score)
        if strict and any(not off_topic(x) and usable(x) for x in ranked):
            ranked.sort(key=lambda x: not (not off_topic(x) and usable(x)))  # stable: keeps score order within groups
        return ranked

    def _semantic(self, db: Session, qvec: np.ndarray, allowed: np.ndarray, pool: int) -> tuple[dict[int, float], str]:
        if db_state.pgvector:
            try:
                literal = "[" + ",".join(f"{v:.6f}" for v in qvec.tolist()) + "]"
                rows = db.execute(text(
                    "SELECT chunk_id, 1 - (embedding <=> CAST(:q AS vector)) AS sim FROM document_chunks "
                    "WHERE is_active AND embedding IS NOT NULL ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"),
                    {"q": literal, "k": pool * 3}).all()
                pos = {d.chunk_id: i for i, d in enumerate(self._docs)}
                result = {pos[r[0]]: float(r[1]) for r in rows if r[0] in pos and allowed[pos[r[0]]]}
                return dict(sorted(result.items(), key=lambda kv: -kv[1])[:pool]), "pgvector"
            except Exception as exc:
                logger.warning("pgvector query failed, using in-memory cosine: %s", exc.__class__.__name__)
                db.rollback()
        sims = self._matrix @ qvec if self._matrix is not None and len(self._matrix) else np.zeros(0)
        sims = np.where(allowed, sims, -1.0)
        top = np.argsort(-sims)[:pool]
        return {int(i): float(sims[i]) for i in top if sims[i] > -1.0}, "in_memory_cosine"

    def search(self, db: Session, query: str, *, intent: str | None, category: str | None, product: str | None,
               taxonomy: TaxonomySnapshot, filters: RetrievalFilters | None = None, top_k: int | None = None,
               query_vector: np.ndarray | None = None) -> RetrievalOutcome:
        started = time.perf_counter()
        self.ensure_index(db)
        s = self.settings
        filters = filters or RetrievalFilters()
        top_k = top_k or s.top_k
        degraded: list[str] = []
        n = len(self._docs)
        if n == 0:
            return RetrievalOutcome([], False, False, "none", False, ["index_empty"], 0.0, 0)

        def build_mask(with_category: bool) -> np.ndarray:
            allowed_cats = taxonomy.categories_under(filters.guided_category) if (with_category and filters.guided_category) else None
            return np.array([
                d.source_id not in filters.exclude_source_ids
                and (filters.source_types is None or d.source_type in filters.source_types)
                and (not filters.general_only or bool(d.extra.get("general")))
                and (allowed_cats is None or d.category in allowed_cats)
                for d in self._docs
            ], dtype=bool)

        allowed = build_mask(True)
        relaxed = False
        if filters.guided_category and allowed.sum() == 0:
            allowed = build_mask(False)
            relaxed = True
            degraded.append("category_filter_relaxed")

        # --- semantic --------------------------------------------------------
        semantic: dict[int, float] = {}
        semantic_used = True
        backend = "in_memory_cosine"
        qvec: np.ndarray | None = None
        try:
            qvec = query_vector if query_vector is not None else self.embeddings.embed_one(query)
            semantic, backend = self._semantic(db, qvec, allowed, s.candidate_pool)
        except Exception as exc:
            semantic_used = False
            backend = "keyword_only"
            degraded.append(f"semantic_unavailable:{exc.__class__.__name__}")

        # --- keyword ---------------------------------------------------------
        bm25, coverage = self._bm25.search(query)
        bm25 = {i: v for i, v in bm25.items() if allowed[i]}
        keyword_used = bool(bm25)
        max_bm25 = max(bm25.values()) if bm25 else 0.0
        keyword_top = sorted(bm25.items(), key=lambda kv: -kv[1])[: s.candidate_pool]

        candidate_ids = set(semantic) | {i for i, _ in keyword_top}
        if semantic_used:
            w_sem, w_kw, w_meta = s.semantic_weight, s.keyword_weight, s.metadata_weight
        else:
            total = s.keyword_weight + s.metadata_weight
            w_sem, w_kw, w_meta = 0.0, s.keyword_weight / total, s.metadata_weight / total

        scored: list[ScoredSource] = []
        for idx in candidate_ids:
            doc = self._docs[idx]
            raw = semantic.get(idx)
            if raw is None and qvec is not None and self._matrix is not None:
                raw = float(self._matrix[idx] @ qvec)
            raw = raw or 0.0
            sem = self.embeddings.calibrate(raw) if semantic_used else 0.0
            kw = (bm25.get(idx, 0.0) / max_bm25 * coverage.get(idx, 0.0)) if max_bm25 > 0 else 0.0
            meta = self.metadata_score(doc, intent, category, product, taxonomy)
            hybrid = w_sem * sem + w_kw * kw + w_meta * meta
            scored.append(ScoredSource(doc.chunk_id, doc.source_id, doc.source_type, doc.title, doc.content, doc.intent,
                                       doc.category, doc.product, doc.quality, doc.extra, raw, sem, kw, meta, hybrid,
                                       None, hybrid))
        scored.sort(key=lambda x: -x.hybrid_score)
        # Keep only the best chunk per source so one article cannot crowd the list.
        unique: list[ScoredSource] = []
        seen: set[str] = set()
        for src in scored:
            if src.source_id in seen:
                continue
            seen.add(src.source_id)
            unique.append(src)
            if len(unique) >= top_k:
                break
        latency = (time.perf_counter() - started) * 1000
        return RetrievalOutcome(unique, semantic_used, keyword_used, backend, relaxed, degraded, latency, len(candidate_ids))
