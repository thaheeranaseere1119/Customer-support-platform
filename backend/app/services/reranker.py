"""Optional cross-encoder reranker with a safe fallback to the hybrid score."""
from __future__ import annotations

import logging
import threading
import time

import numpy as np

from app.config import get_settings
from app.services.retrieval import ScoredSource

logger = logging.getLogger(__name__)


class RerankerService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._model = None
        self._lock = threading.Lock()
        self._attempted = False
        self.error: str | None = None
        self.load_seconds = 0.0

    def load(self) -> bool:
        if not self.settings.reranker_enabled:
            return False
        if self._attempted:
            return self._model is not None
        with self._lock:
            if self._attempted:
                return self._model is not None
            started = time.perf_counter()
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(self.settings.reranker_model, device="cpu")
            except Exception as exc:
                self.error = f"{exc.__class__.__name__}: {exc}"[:300]
                logger.warning("Reranker unavailable, falling back to hybrid ranking: %s", self.error)
            self.load_seconds = round(time.perf_counter() - started, 2)
            self._attempted = True
            return self._model is not None

    @property
    def active(self) -> bool:
        return self.settings.reranker_enabled and self._model is not None

    def rerank(self, query: str, sources: list[ScoredSource]) -> tuple[list[ScoredSource], str]:
        """Return sources sorted by final score and the method used."""
        if not sources:
            return sources, "none"
        method = "hybrid_fallback"
        if self.load():
            try:
                pairs = [(query, f"{s.title}. {s.content}"[:1200]) for s in sources]
                logits = np.asarray(self._model.predict(pairs, show_progress_bar=False), dtype=np.float64)
                probs = 1.0 / (1.0 + np.exp(-logits / self.settings.reranker_temperature))
                w = self.settings.reranker_weight_in_final
                for src, p in zip(sources, probs):
                    src.reranker_score = float(p)
                    src.final_score = w * float(p) + (1 - w) * src.hybrid_score
                method = "cross_encoder"
            except Exception as exc:
                self.error = f"predict failed: {exc.__class__.__name__}"
                logger.warning("Reranker failed at predict time; using hybrid score")
                for src in sources:
                    src.reranker_score = None
                    src.final_score = src.hybrid_score
        else:
            for src in sources:
                src.reranker_score = None
                src.final_score = src.hybrid_score
        return sorted(sources, key=lambda s: -s.final_score), method

    def status(self) -> dict:
        return {"enabled": self.settings.reranker_enabled, "model": self.settings.reranker_model,
                "loaded": self._model is not None, "load_seconds": self.load_seconds, "error": self.error}
