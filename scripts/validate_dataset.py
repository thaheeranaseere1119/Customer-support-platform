"""Validate a support-ticket dataset without loading it.

Checks missing values, empty strings, duplicate ticket/record IDs, invalid intents,
categories, severity, sentiment, dataset split and timestamps.

Usage: python scripts/validate_dataset.py [path] [--rejections data/rejected_rows.csv]
Exit code 1 if any row is rejected.
"""
import argparse
import csv
import json
import sys

import _bootstrap  # noqa: F401

from app.config import DATA_DIR
from app.utils.validation import read_csv_rows, validate_rows, write_rejections


def taxonomy_sets() -> tuple[set[str], set[str]]:
    with (DATA_DIR / "intent_taxonomy.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return {r["name"] for r in rows}, {r["domain_category"] for r in rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", default=str(DATA_DIR / "telecom_support_adaptive_60000.csv"))
    parser.add_argument("--rejections", default=str(DATA_DIR / "rejected_rows.csv"))
    args = parser.parse_args()
    intents, categories = taxonomy_sets()
    columns, rows = read_csv_rows(args.path)
    report = validate_rows(rows, valid_intents=intents, valid_categories=categories, columns=columns)
    summary = report.summary()
    summary["path"] = args.path
    if report.rejected:
        write_rejections(report, args.rejections)
        summary["rejections_file"] = args.rejections
        summary["first_rejections"] = [{"row": r.row_number, "record_id": r.record_id, "reasons": r.reasons}
                                       for r in report.rejected[:10]]
    print(json.dumps(summary, indent=2))
    sys.exit(0 if report.ok else 1)
