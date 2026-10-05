"""Central application configuration.

Every tunable (thresholds, retrieval weights, model names) lives here so that no
other module hard-codes them. Values come from environment variables / `.env`.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = ROOT_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    app_name: str = "Support IQ · Adaptive RAG Telecom Support Resolution Assistant"
    app_version: str = "1.0.0"
    app_env: Literal["development", "test", "production"] = "development"
    demo_mode: bool = True
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_request_bytes: int = 64 * 1024
    max_complaint_chars: int = 2000
    auto_seed: bool = True

    # --- Database ----------------------------------------------------------
    database_url: str = f"sqlite:///{DATA_DIR / 'telecom_support.db'}"
    db_fallback_to_sqlite: bool = True
    sqlite_fallback_url: str = f"sqlite:///{DATA_DIR / 'telecom_support_fallback.db'}"
    pgvector_enabled: bool = True
    db_connect_retries: int = 5
    db_connect_retry_seconds: float = 2.0

    # --- Datasets ----------------------------------------------------------
    dataset_path: str = str(DATA_DIR / "telecom_support_adaptive_60000.csv")
    demo_dataset_path: str = str(DATA_DIR / "tickets.csv")
    knowledge_base_path: str = str(DATA_DIR / "knowledge_base.csv")

    # --- LLM ---------------------------------------------------------------
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: float = 25.0

    # --- Embeddings / reranker --------------------------------------------
    embedding_backend: Literal["auto", "sentence_transformers", "hashing"] = "auto"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_batch_size: int = 64
    reranker_enabled: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # ms-marco cross-encoders emit sharp logits; a temperature keeps scores informative.
    reranker_temperature: float = 3.0
    reranker_weight_in_final: float = 0.6

    # Raw cosine -> [0,1] semantic score calibration (per embedding backend).
    semantic_floor_st: float = 0.20
    semantic_ceiling_st: float = 0.75
    semantic_floor_hashing: float = 0.05
    semantic_ceiling_hashing: float = 0.55

    # --- Retrieval ---------------------------------------------------------
    top_k: int = 10
    candidate_pool: int = 50
    sources_returned: int = 6
    semantic_weight: float = 0.60
    keyword_weight: float = 0.25
    metadata_weight: float = 0.15
    min_relevant_score: float = 0.40
    # Sources from a different top-level topic than the one detected in the question (e.g. Calls tickets for an
    # Internet question that shares the word "dropping") keep this fraction of their final score after reranking.
    topic_mismatch_factor: float = 0.60
    # With no category detected, the closest intent's topic is used as the hint when its similarity reaches this.
    topic_hint_min_similarity: float = 0.50

    # --- Evidence scoring --------------------------------------------------
    known_threshold: float = 0.70
    unknown_threshold: float = 0.45
    evidence_semantic_weight: float = 0.40
    evidence_reranker_weight: float = 0.20
    evidence_intent_weight: float = 0.20
    evidence_source_quality_weight: float = 0.10
    evidence_metadata_weight: float = 0.10
    candidate_min_semantic: float = 0.40
    candidate_min_reranker: float = 0.15

    # --- Classification ----------------------------------------------------
    intent_example_threshold_st: float = 0.62
    intent_example_threshold_hashing: float = 0.60

    # --- Adaptive workflow -------------------------------------------------
    max_resolution_attempts: int = 3

    # --- Emerging issues ---------------------------------------------------
    emerging_similarity_threshold: float = 0.62
    emerging_similarity_threshold_hashing: float = 0.35
    emerging_min_cluster_size: int = 3

    # --- Memory ------------------------------------------------------------
    memory_max_messages: int = 10
    memory_max_chars: int = 1800

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        """Relative paths are anchored at the project root, wherever the process starts."""
        for attr in ("dataset_path", "demo_dataset_path", "knowledge_base_path"):
            value = Path(getattr(self, attr))
            if not value.is_absolute():
                object.__setattr__(self, attr, str((ROOT_DIR / value).resolve()))
        for attr in ("database_url", "sqlite_fallback_url"):
            url = getattr(self, attr)
            if url.startswith("sqlite:///") and not url.startswith("sqlite:////") and ":memory:" not in url:
                rel = url[len("sqlite:///"):]
                object.__setattr__(self, attr, f"sqlite:///{(ROOT_DIR / rel).resolve()}")
        return self

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if not 0 <= self.unknown_threshold < self.known_threshold <= 1:
            raise ValueError("Require 0 <= UNKNOWN_THRESHOLD < KNOWN_THRESHOLD <= 1")
        retrieval = self.semantic_weight + self.keyword_weight + self.metadata_weight
        if abs(retrieval - 1.0) > 1e-6:
            raise ValueError("SEMANTIC_WEIGHT + KEYWORD_WEIGHT + METADATA_WEIGHT must equal 1.0")
        evidence = (
            self.evidence_semantic_weight
            + self.evidence_reranker_weight
            + self.evidence_intent_weight
            + self.evidence_source_quality_weight
            + self.evidence_metadata_weight
        )
        if abs(evidence - 1.0) > 1e-6:
            raise ValueError("Evidence weights must sum to 1.0")
        if self.max_resolution_attempts < 1:
            raise ValueError("MAX_RESOLUTION_ATTEMPTS must be >= 1")
        return self

    # --- Derived -----------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_api_key.get_secret_value().strip())

    @property
    def ai_mode(self) -> bool:
        """AI mode requires DEMO_MODE=false and a configured Gemini key."""
        return (not self.demo_mode) and self.has_gemini_key

    @property
    def mode_label(self) -> str:
        return "AI MODE" if self.ai_mode else "DEMO MODE"

    def classify_evidence(self, score: float) -> str:
        """Single source of truth for KNOWN / UNCERTAIN / UNKNOWN thresholds."""
        if score >= self.known_threshold:
            return "known"
        if score >= self.unknown_threshold:
            return "uncertain"
        return "unknown"


# Runtime-tunable fields exposed via the Settings page (validated on update).
RUNTIME_TUNABLE = (
    "known_threshold",
    "unknown_threshold",
    "semantic_weight",
    "keyword_weight",
    "metadata_weight",
    "top_k",
    "max_resolution_attempts",
    "reranker_enabled",
    "emerging_similarity_threshold",
    "emerging_min_cluster_size",
)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def update_runtime_settings(changes: dict) -> Settings:
    """Apply validated runtime overrides to the cached settings object."""
    current = get_settings()
    data = current.model_dump()
    for key, value in changes.items():
        if key not in RUNTIME_TUNABLE:
            raise ValueError(f"Setting '{key}' cannot be changed at runtime")
        data[key] = value
    validated = Settings.model_validate(data)
    for key in changes:
        object.__setattr__(current, key, getattr(validated, key))
    return current

