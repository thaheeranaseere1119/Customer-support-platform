"""Embeddings, hybrid retrieval, metadata filtering, reranking and fallbacks."""
import numpy as np

from app.config import get_settings
from app.services.embeddings import HashingEmbedder
from app.services.retrieval import BM25Index, RetrievalFilters
from app.services.taxonomy import taxonomy_service


def test_embeddings_are_normalised_and_cached(services):
    emb = services.embeddings
    vecs = emb.embed(["broadband keeps dropping", "charged twice on my bill"])
    assert vecs.shape == (2, emb.dim)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-4)
    before = emb.status()["cache_entries"]
    emb.embed(["broadband keeps dropping"])
    assert emb.status()["cache_entries"] == before  # cache hit: no re-embedding


def test_semantic_similarity_orders_related_text(services):
    emb = services.embeddings
    q, a, b = emb.embed(["my internet connection keeps cutting out", "broadband disconnects intermittently",
                         "I want to update my email address"])
    assert float(q @ a) > float(q @ b)


def test_hashing_fallback_is_deterministic():
    hasher = HashingEmbedder(384)
    one, two = hasher.encode(["router keeps restarting"]), hasher.encode(["router keeps restarting"])
    assert np.array_equal(one, two)
    assert abs(np.linalg.norm(one[0]) - 1.0) < 1e-5


def test_bm25_ranks_keyword_matches():
    index = BM25Index()
    index.build(["sim card not detected", "broadband slow in evening", "bill charged twice"])
    scores, coverage = index.search("sim not detected")
    assert max(scores, key=scores.get) == 0
    assert coverage[0] == 1.0


def _search(services, db, text, **kw):
    taxonomy = taxonomy_service.get(db)
    analysis = services.classifier.classify(db, text)
    return services.retrieval.search(db, text, intent=analysis.intent, category=analysis.category,
                                     product=analysis.product, taxonomy=taxonomy, **kw)


def test_hybrid_score_uses_configured_weights(services, db):
    s = get_settings()
    outcome = _search(services, db, "My broadband keeps disconnecting every evening")
    assert outcome.semantic_used and outcome.keyword_used
    for src in outcome.sources:
        expected = s.semantic_weight * src.semantic_score + s.keyword_weight * src.keyword_score + s.metadata_weight * src.metadata_score
        assert abs(src.hybrid_score - expected) < 1e-6
    assert outcome.sources[0].intent == "broadband_disconnects"


def test_metadata_filter_restricts_category(services, db):
    outcome = _search(services, db, "it keeps failing", filters=RetrievalFilters(guided_category="Billing"))
    assert outcome.sources
    assert all(src.category == "Billing" for src in outcome.sources)


def test_excluded_sources_are_not_returned(services, db):
    first = _search(services, db, "My SIM is not detected")
    excluded = {first.sources[0].source_id}
    second = _search(services, db, "My SIM is not detected", filters=RetrievalFilters(exclude_source_ids=excluded))
    assert excluded.isdisjoint({s.source_id for s in second.sources})


def test_keyword_only_fallback_when_embedding_fails(services, db, monkeypatch):
    def boom(_text):
        raise RuntimeError("model offline")
    monkeypatch.setattr(services.embeddings, "embed_one", boom)
    outcome = _search(services, db, "sim not detected")
    assert outcome.semantic_used is False
    assert outcome.vector_backend == "keyword_only"
    assert outcome.sources and outcome.sources[0].intent == "sim_not_detected"


def test_reranker_scores_or_falls_back(services, db):
    outcome = _search(services, db, "My calls keep dropping")
    ranked, method = services.reranker.rerank("My calls keep dropping", outcome.sources)
    assert method in ("cross_encoder", "hybrid_fallback")
    assert [s.final_score for s in ranked] == sorted([s.final_score for s in ranked], reverse=True)
    if method == "cross_encoder":
        assert all(0.0 <= s.reranker_score <= 1.0 for s in ranked)


def test_reranker_failure_falls_back_to_hybrid(services, db, monkeypatch):
    outcome = _search(services, db, "My calls keep dropping")

    class Broken:
        def predict(self, *_a, **_k):
            raise RuntimeError("boom")
    monkeypatch.setattr(services.reranker, "_model", Broken())
    monkeypatch.setattr(services.reranker, "_attempted", True)
    ranked, method = services.reranker.rerank("x", outcome.sources)
    assert method == "hybrid_fallback"
    assert all(s.final_score == s.hybrid_score for s in ranked)


def test_held_out_and_calibration_tickets_never_indexed(db):
    from sqlalchemy import select

    from app.models import DocumentChunk, Ticket
    indexed = set(db.scalars(select(DocumentChunk.source_id).where(DocumentChunk.source_type == "historical_ticket")))
    protected = set(db.scalars(select(Ticket.ticket_id).where(Ticket.dataset_split.in_(("held_out_test", "calibration")))))
    assert protected and indexed.isdisjoint(protected)
