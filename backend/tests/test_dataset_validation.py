"""Dataset validation rejects malformed rows instead of silently accepting them."""
import csv
from pathlib import Path

from app.utils.validation import validate_rows

ROOT = Path(__file__).resolve().parents[2]
INTENTS = {"broadband_slow", "billing_dispute"}
CATEGORIES = {"CONNECTIVITY", "BILLING"}


def good_row(**overrides):
    with (ROOT / "data" / "tickets.csv").open(newline="", encoding="utf-8") as fh:
        row = next(r for r in csv.DictReader(fh) if r["intent"] == "billing_dispute")
    row.update(overrides)
    return row


def check(rows):
    return validate_rows(rows, valid_intents=INTENTS, valid_categories=CATEGORIES, columns=list(rows[0].keys()))


def test_valid_row_passes():
    report = check([good_row()])
    assert report.ok and len(report.valid_rows) == 1


def test_each_issue_type_is_detected():
    rows = [
        good_row(record_id="R1", ticket_id="T1", intent="made_up_intent"),
        good_row(record_id="R2", ticket_id="T2", category="NOT_A_CATEGORY"),
        good_row(record_id="R3", ticket_id="T3", severity="catastrophic"),
        good_row(record_id="R4", ticket_id="T4", sentiment="ecstatic"),
        good_row(record_id="R5", ticket_id="T5", dataset_split="production"),
        good_row(record_id="R6", ticket_id="T6", created_at="31/31/26"),
        good_row(record_id="R7", ticket_id="T7", customer_complaint="   "),
        good_row(record_id="R8", ticket_id="T7"),
        good_row(record_id="R8", ticket_id="T9"),
        good_row(record_id="R10", ticket_id="T10", evidence_score="1.7"),
    ]
    report = check(rows)
    issues = report.issue_counts
    for key in ("invalid_intent", "invalid_category", "invalid_severity", "invalid_sentiment", "invalid_dataset_split",
                "invalid_timestamp", "empty_string", "duplicate_ticket_id", "duplicate_record_id",
                "evidence_score_out_of_range"):
        assert issues[key] >= 1, key
    assert not report.valid_rows


def test_missing_columns_reported():
    row = good_row()
    row.pop("intent")
    report = validate_rows([row], valid_intents=INTENTS, valid_categories=CATEGORIES, columns=list(row.keys()))
    assert "intent" in report.missing_columns and not report.ok


def test_missing_value_detected():
    row = good_row()
    row["resolution"] = None
    report = check([row])
    assert report.issue_counts["missing_value"] == 1
