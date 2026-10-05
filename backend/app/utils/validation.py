"""Dataset validation and normalisation.

Malformed rows are never silently accepted: every rejected row is reported with
its row number and the reasons, and ingestion can be run in --strict mode.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REQUIRED_COLUMNS = [
    "record_id", "ticket_id", "dataset_split", "customer_complaint", "category", "intent", "product", "severity",
    "sentiment", "retrieval_text", "resolution", "resolution_attempt", "resolution_status", "evidence_status",
    "evidence_score", "citation_source_id", "citation_type", "customer_feedback", "human_verification_status",
    "knowledge_state", "emerging_class_signal", "escalation_required", "created_at", "source", "source_type",
]
OPTIONAL_COLUMNS = ["customer_id", "language", "interaction_mode", "channel", "entities_json", "conversation_context",
                    "previous_troubleshooting"]
# Columns allowed to be empty strings (free-text context that may legitimately be blank).
NULLABLE = {"customer_id", "conversation_context", "previous_troubleshooting"}

VALID_SPLITS = {"development", "calibration", "held_out_test"}
VALID_SEVERITY = {"low", "medium", "high", "critical"}
VALID_SENTIMENT = {"positive", "neutral", "negative", "frustrated", "urgent"}
VALID_RESOLUTION_STATUS = {"resolved", "candidate", "escalated", "unresolved"}
VALID_EVIDENCE_STATUS = {"sufficient", "insufficient", "uncertain"}
VALID_KNOWLEDGE_STATE = {"trusted", "candidate", "rejected"}
VALID_YES_NO = {"yes", "no", "true", "false"}
DATE_FORMATS = ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def parse_timestamp(value: str) -> datetime | None:
    value = (value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class RejectedRow:
    row_number: int
    record_id: str
    reasons: list[str]


@dataclass
class ValidationReport:
    total_rows: int = 0
    valid_rows: list[dict] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    issue_counts: Counter = field(default_factory=Counter)
    missing_columns: list[str] = field(default_factory=list)
    split_counts: Counter = field(default_factory=Counter)

    @property
    def ok(self) -> bool:
        return not self.missing_columns and not self.rejected

    def summary(self) -> dict:
        return {
            "total_rows": self.total_rows,
            "valid_rows": len(self.valid_rows),
            "rejected_rows": len(self.rejected),
            "missing_columns": self.missing_columns,
            "issues": dict(self.issue_counts),
            "split_counts": dict(self.split_counts),
        }


def _norm(value) -> str:
    return "" if value is None else str(value).strip()


def validate_rows(rows: list[dict], *, valid_intents: set[str], valid_categories: set[str],
                  existing_record_ids: set[str] | None = None, existing_ticket_ids: set[str] | None = None,
                  columns: list[str] | None = None) -> ValidationReport:
    report = ValidationReport(total_rows=len(rows))
    cols = columns if columns is not None else (list(rows[0].keys()) if rows else [])
    report.missing_columns = [c for c in REQUIRED_COLUMNS if c not in cols]
    if report.missing_columns:
        report.issue_counts["missing_columns"] = len(report.missing_columns)
        return report

    seen_records = Counter(_norm(r.get("record_id")) for r in rows)
    seen_tickets = Counter(_norm(r.get("ticket_id")) for r in rows)
    existing_record_ids = existing_record_ids or set()
    existing_ticket_ids = existing_ticket_ids or set()

    for idx, raw in enumerate(rows, start=2):  # row 1 is the header
        reasons: list[str] = []
        row = {k: _norm(v) for k, v in raw.items() if k is not None}
        for col in REQUIRED_COLUMNS + [c for c in OPTIONAL_COLUMNS if c in row]:
            if col not in row or raw.get(col) is None:
                reasons.append(f"missing_value:{col}")
            elif row[col] == "" and col not in NULLABLE:
                reasons.append(f"empty_string:{col}")

        rid, tid = row.get("record_id", ""), row.get("ticket_id", "")
        if rid and (seen_records[rid] > 1 or rid in existing_record_ids):
            reasons.append("duplicate_record_id")
        if tid and (seen_tickets[tid] > 1 or tid in existing_ticket_ids):
            reasons.append("duplicate_ticket_id")

        for col, valid, label in (
            ("intent", valid_intents, "invalid_intent"),
            ("category", valid_categories, "invalid_category"),
        ):
            if row.get(col) and row[col] not in valid:
                reasons.append(label)
        lower_checks = (
            ("severity", VALID_SEVERITY, "invalid_severity"),
            ("sentiment", VALID_SENTIMENT, "invalid_sentiment"),
            ("dataset_split", VALID_SPLITS, "invalid_dataset_split"),
            ("resolution_status", VALID_RESOLUTION_STATUS, "invalid_resolution_status"),
            ("evidence_status", VALID_EVIDENCE_STATUS, "invalid_evidence_status"),
            ("knowledge_state", VALID_KNOWLEDGE_STATE, "invalid_knowledge_state"),
            ("escalation_required", VALID_YES_NO, "invalid_escalation_required"),
        )
        for col, valid, label in lower_checks:
            if row.get(col):
                row[col] = row[col].lower()
                if row[col] not in valid:
                    reasons.append(label)

        created = parse_timestamp(row.get("created_at", ""))
        if row.get("created_at") and created is None:
            reasons.append("invalid_timestamp")

        try:
            score = float(row.get("evidence_score", ""))
            if not 0.0 <= score <= 1.0:
                reasons.append("evidence_score_out_of_range")
        except ValueError:
            score = 0.0
            if row.get("evidence_score"):
                reasons.append("invalid_evidence_score")
        try:
            attempt = int(float(row.get("resolution_attempt", "")))
            if attempt < 1:
                reasons.append("invalid_resolution_attempt")
        except ValueError:
            attempt = 1
            if row.get("resolution_attempt"):
                reasons.append("invalid_resolution_attempt")

        entities: dict = {}
        if row.get("entities_json"):
            try:
                parsed = json.loads(row["entities_json"])
                entities = parsed if isinstance(parsed, dict) else {"values": parsed}
            except json.JSONDecodeError:
                reasons.append("invalid_entities_json")

        if reasons:
            report.rejected.append(RejectedRow(idx, rid or f"row-{idx}", reasons))
            for r in reasons:
                report.issue_counts[r.split(":")[0]] += 1
            continue

        row["created_at_parsed"] = created
        row["evidence_score_parsed"] = score
        row["resolution_attempt_parsed"] = attempt
        row["entities_parsed"] = entities
        row["escalation_parsed"] = row["escalation_required"] in {"yes", "true"}
        report.valid_rows.append(row)
        report.split_counts[row["dataset_split"]] += 1
    return report


def read_csv_rows(path: str | Path) -> tuple[list[str], list[dict]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def write_rejections(report: ValidationReport, path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["row_number", "record_id", "reasons"])
        for rej in report.rejected:
            writer.writerow([rej.row_number, rej.record_id, ";".join(rej.reasons)])
