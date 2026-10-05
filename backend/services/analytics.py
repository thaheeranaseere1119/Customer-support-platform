"""Dashboard and analytics aggregates."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CandidateCase,
    EmergingIssue,
    EvaluationRun,
    Feedback,
    IntentTaxonomy,
    KnowledgeArticle,
    SupportCase,
    Ticket,
)
from app.models._common import utcnow
from app.services.adaptive_resolution import case_summary
from app.services.emerging_issue import issue_to_dict
from app.services.evaluation import run_to_dict


def _count(db: Session, stmt) -> int:
    return int(db.scalar(stmt) or 0)


def overview(db: Session) -> dict:
    tickets_total = _count(db, select(func.count()).select_from(Ticket))
    by_split = dict(db.execute(select(Ticket.dataset_split, func.count()).group_by(Ticket.dataset_split)).all())
    cases_total = _count(db, select(func.count()).select_from(SupportCase))
    by_status = dict(db.execute(select(SupportCase.status, func.count()).group_by(SupportCase.status)).all())
    by_evidence = dict(db.execute(select(SupportCase.evidence_status, func.count()).group_by(SupportCase.evidence_status)).all())
    resolved_dataset = _count(db, select(func.count()).select_from(Ticket).where(Ticket.resolution_status == "resolved"))
    resolved_live = by_status.get("resolved", 0) + by_status.get("candidate_submitted", 0)
    feedback = dict(db.execute(select(Feedback.outcome, func.count()).group_by(Feedback.outcome)).all())
    fb_total = sum(feedback.values())
    kb = dict(db.execute(select(KnowledgeArticle.status, func.count()).where(KnowledgeArticle.is_latest.is_(True))
                         .group_by(KnowledgeArticle.status)).all())
    candidates = dict(db.execute(select(CandidateCase.status, func.count()).group_by(CandidateCase.status)).all())
    emerging = dict(db.execute(select(EmergingIssue.status, func.count()).group_by(EmergingIssue.status)).all())

    since = utcnow() - timedelta(days=13)
    activity_rows = db.execute(select(func.date(SupportCase.created_at), SupportCase.evidence_status, func.count())
                               .where(SupportCase.created_at >= since.replace(hour=0, minute=0, second=0, microsecond=0))
                               .group_by(func.date(SupportCase.created_at), SupportCase.evidence_status)).all()
    days = [(since + timedelta(days=i)).date().isoformat() for i in range(14)]
    activity = {d: {"date": d, "known": 0, "uncertain": 0, "unknown": 0} for d in days}
    for day, status, count in activity_rows:
        key = str(day)[:10]
        if key in activity and status in activity[key]:
            activity[key][status] += count

    intent_dist = db.execute(select(SupportCase.intent, func.count()).group_by(SupportCase.intent)
                             .order_by(func.count().desc()).limit(8)).all()
    dataset_dist = db.execute(select(Ticket.category, func.count()).group_by(Ticket.category)
                              .order_by(func.count().desc())).all()
    recent = db.scalars(select(SupportCase).order_by(SupportCase.created_at.desc()).limit(8)).all()
    issues = db.scalars(select(EmergingIssue).where(EmergingIssue.status.in_(("NEW", "UNDER_REVIEW")))
                        .order_by(EmergingIssue.occurrences.desc()).limit(4)).all()
    latest_eval = db.scalar(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(1))
    avg_attempts = db.scalar(select(func.avg(SupportCase.current_attempt))) or 0.0
    avg_latency = db.scalar(select(func.avg(SupportCase.latency_ms))) or 0.0
    avg_evidence = db.scalar(select(func.avg(SupportCase.evidence_score))) or 0.0

    success_rate = (feedback.get("solved", 0) / fb_total) if fb_total else None
    return {
        "stats": {
            "total_tickets": tickets_total + cases_total,
            "dataset_tickets": tickets_total,
            "live_cases": cases_total,
            "resolved_cases": resolved_dataset + resolved_live,
            "resolved_live_cases": resolved_live,
            "unknown_issues": by_evidence.get("unknown", 0),
            "uncertain_cases": by_evidence.get("uncertain", 0),
            "knowledge_articles": kb.get("ACTIVE", 0),
            "draft_articles": kb.get("DRAFT", 0),
            "pending_candidates": candidates.get("pending_review", 0),
            "approved_candidates": candidates.get("approved", 0),
            "rejected_candidates": candidates.get("rejected", 0),
            "emerging_open": emerging.get("NEW", 0) + emerging.get("UNDER_REVIEW", 0),
            "intents": _count(db, select(func.count()).select_from(IntentTaxonomy).where(IntentTaxonomy.status == "active")),
            "resolution_success_rate": round(success_rate, 4) if success_rate is not None else None,
            "escalation_rate": round(by_status.get("escalated", 0) / cases_total, 4) if cases_total else None,
            "average_attempts": round(float(avg_attempts), 3),
            "average_response_ms": round(float(avg_latency), 1),
            "average_evidence_score": round(float(avg_evidence), 4),
        },
        "dataset_split_counts": by_split,
        "case_status_counts": by_status,
        "evidence_status_counts": by_evidence,
        "feedback_counts": feedback,
        "knowledge_status_counts": kb,
        "candidate_status_counts": candidates,
        "emerging_status_counts": emerging,
        "activity": list(activity.values()),
        "intent_distribution": [{"intent": i, "count": c} for i, c in intent_dist],
        "dataset_category_distribution": [{"category": c, "count": n} for c, n in dataset_dist],
        "recent_cases": [case_summary(c) for c in recent],
        "emerging_issues": [issue_to_dict(i) for i in issues],
        "latest_evaluation": run_to_dict(latest_eval) if latest_eval else None,
    }
