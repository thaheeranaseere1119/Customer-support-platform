"""Create / upgrade the database schema (idempotent). Enables pgvector on PostgreSQL.

Usage: python scripts/migrate.py [--reset]
"""
import argparse
import json
import sys

import _bootstrap  # noqa: F401

from app.database import create_all, db_state, init_engine
from app.ingestion import reset_database
from app.utils.logging import configure_logging

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables (destroys data)")
    args = parser.parse_args()
    configure_logging("WARNING", stream=sys.stderr)
    init_engine()
    reset_database() if args.reset else create_all()
    print(json.dumps({"database": db_state.url_backend, "pgvector": db_state.pgvector,
                      "using_fallback": db_state.using_fallback, "reset": args.reset}, indent=2))
