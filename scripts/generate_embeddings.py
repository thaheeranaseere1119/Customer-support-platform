"""(Re)generate embeddings for any chunk that is missing one or was embedded by a
different model, then rebuild the index. Unchanged chunks are not re-embedded.

Usage: python scripts/generate_embeddings.py
"""
import json
import sys

import scripts._bootstrap as _bootstrap  # noqa: F401

from app.database import init_engine, session_scope
from app.ingestion import embed_pending
from app.services.embeddings import get_embedding_service
from app.services.retrieval import RetrievalService
from app.utils.logging import configure_logging

if __name__ == "__main__":
    configure_logging("WARNING", stream=sys.stderr)
    init_engine()
    embeddings = get_embedding_service()
    with session_scope() as db:
        result = embed_pending(db, embeddings)
        retrieval = RetrievalService(embeddings)
        retrieval.ensure_index(db)
        result["index"] = retrieval.stats()
    print(json.dumps(result, indent=2, default=str))
