"""Run the offline evaluation on a held-out or calibration split and store it.

Usage: python scripts/evaluate.py [--split held_out_test|calibration] [--limit 120]
"""
import argparse
import json
import sys

import _bootstrap  # noqa: F401

from app.database import init_engine, session_scope
from app.dependencies import get_container
from app.utils.logging import configure_logging

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="held_out_test", choices=["held_out_test", "calibration"])
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    configure_logging("WARNING", stream=sys.stderr)
    init_engine()
    with session_scope() as db:
        result = get_container().evaluation.run(db, split=args.split, limit=args.limit, seed=args.seed)
    metrics = result["metrics"]
    metrics["classification"].pop("per_class", None)
    print(json.dumps(result, indent=2, default=str))
