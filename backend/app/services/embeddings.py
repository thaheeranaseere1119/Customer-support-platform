"""EmbeddingService: local sentence-transformers model with a safe fallback.

* Loads the configured model once (thread-safe, cached singleton).
* Batches encodes and caches vectors by text hash so nothing is re-embedded
  unnecessarily.
* If sentence-transformers / the model is unavailable, falls back to a
  deterministic hashed n-gram embedder so the system keeps working offline.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict

import numpy as np

from app.config import get_settings
from app.utils.text import stem, tokenize

logger = logging.getLogger(__name__)


class HashingEmbedder:
    """Deterministic lexical embedding (word uni/bi-grams + char 4-grams)."""

    name = "hashing-ngram-v1"

    def __init__(self, dim: int):
        self.dim = dim

    def _index(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        return value % self.dim, (1.0 if (value >> 63) & 1 else -1.0)

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            words = [stem(t) for t in tokenize(text)]
            features: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words]
            features += [(f"b:{a}_{b}", 0.7) for a, b in zip(words, words[1:])]
            for w in words:
                padded = f"#{w}#"
                features += [(f"c:{padded[i:i + 4]}", 0.25) for i in range(max(1, len(padded) - 3))]
            for feat, weight in features:
                idx, sign = self._index(feat)
                out[row, idx] += sign * weight
            norm = np.linalg.norm(out[row])
            if norm > 0:
                out[row] /= norm
        return out


class EmbeddingService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._model = None
        self._fallback = HashingEmbedder(self.settings.embedding_dim)
        self._lock = threading.Lock()
        self._loaded = False
        self.backend = "uninitialised"
        self.model_name = ""
        self.error: str | None = None
        self.load_seconds = 0.0
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._cache_limit = 20000

    # ------------------------------------------------------------------ loading
    def load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            started = time.perf_counter()
            preference = self.settings.embedding_backend
            if preference in ("auto", "sentence_transformers"):
                try:
                    from sentence_transformers import SentenceTransformer

                    model = SentenceTransformer(self.settings.embedding_model, device="cpu")
                    getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
                    dim = int(getter() or 0)
                    if dim != self.settings.embedding_dim:
                        raise ValueError(f"model dimension {dim} != EMBEDDING_DIM {self.settings.embedding_dim}")
                    self._model = model
                    self.backend = "sentence_transformers"
                    self.model_name = self.settings.embedding_model
                except Exception as exc:
                    self.error = f"{exc.__class__.__name__}: {exc}"[:300]
                    logger.warning("Embedding model unavailable, using hashing fallback: %s", self.error)
            if self._model is None:
                self.backend = "hashing"
                self.model_name = self._fallback.name
            self.load_seconds = round(time.perf_counter() - started, 2)
            self._loaded = True

    @property
    def model_id(self) -> str:
        self.load()
        return f"{self.backend}:{self.model_name}"

    @property
    def dim(self) -> int:
        return self.settings.embedding_dim

    def semantic_bounds(self) -> tuple[float, float]:
        """Raw-cosine calibration range for the active backend."""
        self.load()
        s = self.settings
        if self.backend == "sentence_transformers":
            return s.semantic_floor_st, s.semantic_ceiling_st
        return s.semantic_floor_hashing, s.semantic_ceiling_hashing

    def calibrate(self, cosine: float) -> float:
        floor, ceiling = self.semantic_bounds()
        return float(np.clip((cosine - floor) / (ceiling - floor), 0.0, 1.0))

    def intent_example_threshold(self) -> float:
        self.load()
        s = self.settings
        return s.intent_example_threshold_st if self.backend == "sentence_transformers" else s.intent_example_threshold_hashing

    def general_checklist_threshold(self) -> float:
        """Calibrated on the sentence-transformers scale; the hashed fallback cannot tell close from far apart."""
        self.load()
        return self.settings.general_checklist_min_semantic if self.backend == "sentence_transformers" else 0.0

    def emerging_threshold(self) -> float:
        self.load()
        s = self.settings
        return s.emerging_similarity_threshold if self.backend == "sentence_transformers" else s.emerging_similarity_threshold_hashing

    # ---------------------------------------------------------------- encoding
    def _key(self, text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return L2-normalised float32 vectors, shape (len(texts), dim)."""
        self.load()
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        keys = [self._key(t or "") for t in texts]
        missing = [i for i, k in enumerate(keys) if k not in self._cache]
        if missing:
            pending = [texts[i] or "" for i in missing]
            vectors = self._encode(pending)
            for i, vec in zip(missing, vectors):
                self._cache[keys[i]] = vec
            while len(self._cache) > self._cache_limit:
                self._cache.popitem(last=False)
        result = np.vstack([self._cache[k] for k in keys]).astype(np.float32)
        return result

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def _encode(self, texts: list[str]) -> np.ndarray:
        if self._model is not None:
            try:
                vecs = self._model.encode(
                    texts, batch_size=self.settings.embedding_batch_size, normalize_embeddings=True,
                    show_progress_bar=False, convert_to_numpy=True,
                )
                return np.asarray(vecs, dtype=np.float32)
            except Exception as exc:  # never crash the request on an encoder failure
                logger.error("Embedding model failed at encode time: %s", exc.__class__.__name__)
                raise
        return self._fallback.encode(texts)

    def status(self) -> dict:
        return {
            "backend": self.backend,
            "model": self.model_name,
            "dimension": self.dim,
            "loaded": self._loaded,
            "load_seconds": self.load_seconds,
            "cache_entries": len(self._cache),
            "error": self.error,
        }


_service: EmbeddingService | None = None
_service_lock = threading.Lock()


def get_embedding_service() -> EmbeddingService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = EmbeddingService()
    return _service


def reset_embedding_service() -> None:
    global _service
    _service = None
