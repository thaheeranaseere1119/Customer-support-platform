"""Ingest data: validate -> normalise -> reject malformed rows -> insert tickets ->
insert KB -> chunk documents -> generate embeddings -> store embeddings -> build index.

Usage:
  python scripts/ingest_data.py                       # full 60K dataset if present, else data/tickets.csv
  python scripts/ingest_data.py --dataset data/tickets.csv --reset
  python scripts/ingest_data.py --strict              # fail if any row is malformed
  python scripts/ingest_data.py --skip-embeddings     # load data only
"""
import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from app.database import init_engine
from app.ingestion import run_ingestion
from app.utils.logging import configure_logging

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    parser.add_argument("--strict", action="store_true", help="abort if any row fails validation")
    parser.add_argument("--skip-embeddings", action="store_true")
    parser.add_argument("--no-demo-supplement", action="store_true",
                        help="do not add the hand-authored DEMO- tickets from data/tickets.csv")
    args = parser.parse_args()
    configure_logging("WARNING", stream=sys.stderr)
    init_engine()
    summary = run_ingestion(args.dataset, reset=args.reset, strict=args.strict, skip_embeddings=args.skip_embeddings,
                            demo_supplement=not args.no_demo_supplement)
    print(json.dumps(summary, indent=2, default=str))
