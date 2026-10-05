"""Emerging issue discovery.

Unknown / low-evidence cases and pending candidate knowledge are embedded and
greedily clustered by cosine similarity. A cluster whose occurrences reach
EMERGING_MIN_CLUSTER_SIZE becomes an EmergingIssue with status NEW. Nothing is
promoted to a production intent without a human creating it explicitly.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CandidateCase, EmergingIssue, EmergingIssueMember, SupportCase
from app.models._common import utcnow
from app.services.embeddings import EmbeddingService
from app.utils.errors import ConflictError, NotFoundError, ValidationFailed
from app.utils.logging import short_id
from app.utils.text import STOPWORDS, strip_synthetic_tag, tokenize

GENERIC = STOPWORDS | {
    "issue", "issues", "problem", "problems", "working", "work", "works", "help", "need", "not", "no", "but", "customer",
    "still", "even", "though", "after", "since", "show", "shows", "says", "said", "stopped", "keep", "keeps", "get",
    "gets", "getting", "when", "only", "never", "cannot", "does", "phone", "while", "today", "time", "happens",
    "repeatedly", "like", "would", "want", "support", "resolving", "assistance", "next", "step", "guide", "through",
    "approved", "tell", "basic", "checks", "checked", "settings", "started", "recently", "affecting", "normal", "usage",
    "continued", "despite", "present", "intermittent", "intermittently", "past", "week", "last", "two", "days", "morning",
    "yesterday", "right", "now", "one", "specific", "itself", "fine", "where", "every", "same", "latest", "during",
    "troubleshoot", "already", "connected", "evening", "night", "today", "issue", "longer", "missing",
}


@dataclass
class PoolItem:
    member_type: str
    member_id: str
    complaint: str
    evidence_score: float
    weight: int
    category: str
    vector: np.ndarray


def issue_to_dict(issue: EmergingIssue, members: list[EmergingIssueMember] | None = None) -> dict:
    data = {
        "id": issue.id, "pattern_name": issue.pattern_name, "description": issue.description, "status": issue.status,
        "occurrences": issue.occurrences, "avg_evidence_score": round(issue.avg_evidence_score, 4),
        "keywords": issue.keywords, "example_complaints": issue.example_complaints,
        "suggested_intent_name": issue.suggested_intent_name, "suggested_category": issue.suggested_category,
        "created_intent": issue.created_intent, "created_article_id": issue.created_article_id,
        "review_notes": issue.review_notes,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
    }
    if members is not None:
        data["members"] = [{"member_type": m.member_type, "member_id": m.member_id, "complaint": m.complaint,
                            "similarity": round(m.similarity, 4), "evidence_score": round(m.evidence_score, 4),
                            "weight": m.weight} for m in members]
    return data


class EmergingIssueService:
    def __init__(self, embeddings: EmbeddingService):
        self.embeddings = embeddings
        self.settings = get_settings()

    def _frozen_member_ids(self, db: Session) -> set[str]:
        rows = db.execute(select(EmergingIssueMember.member_id).join(
            EmergingIssue, EmergingIssue.id == EmergingIssueMember.emerging_issue_id).where(
            EmergingIssue.status.in_(("APPROVED", "REJECTED")))).all()
        return {r[0] for r in rows}

    def _ensure_vector(self, row) -> np.ndarray:
        model_id = self.embeddings.model_id
        if row.embedding is None or row.embedding_model != model_id or len(row.embedding) != self.embeddings.dim:
            row.embedding = self.embeddings.embed_one(strip_synthetic_tag(row.complaint))
            row.embedding_model = model_id
        return np.asarray(row.embedding, dtype=np.float32)

    def _pool(self, db: Session) -> list[PoolItem]:
        frozen = self._frozen_member_ids(db)
        items: list[PoolItem] = []
        cases = db.scalars(select(SupportCase).where(
            (SupportCase.evidence_status == "unknown") |
            ((SupportCase.evidence_status == "uncertain") & (SupportCase.intent == "unknown")))).all()
        for case in cases:
            if case.id in frozen:
                continue
            items.append(PoolItem("case", case.id, case.complaint, case.evidence_score, 1, case.category,
                                  self._ensure_vector(case)))
        candidates = db.scalars(select(CandidateCase).where(CandidateCase.status == "pending_review").where(
            (CandidateCase.emerging_signal.is_(True)) | (CandidateCase.intent == "unknown"))).all()
        case_ids = {i.member_id for i in items}
        for cand in candidates:
            if cand.id in frozen or (cand.case_id and cand.case_id in case_ids):
                continue
            items.append(PoolItem("candidate", cand.id, strip_synthetic_tag(cand.complaint), cand.evidence_score,
                                  max(1, cand.occurrences), cand.category, self._ensure_vector(cand)))
        db.flush()
        return items

    @staticmethod
    def _keywords(texts: list[tuple[str, int]], top: int = 4) -> list[str]:
        counts: Counter = Counter()
        for text, weight in texts:
            for token in set(tokenize(text)):
                if token not in GENERIC and len(token) > 2 and not token.isdigit():
                    counts[token] += weight
        return [w for w, _ in counts.most_common(top)]

    def detect(self, db: Session) -> dict:
        s = self.settings
        threshold = self.embeddings.emerging_threshold()
        pool = self._pool(db)
        clusters: list[dict] = []
        for item in sorted(pool, key=lambda i: -i.weight):
            best, best_sim = None, -1.0
            for cluster in clusters:
                sim = float(cluster["centroid"] @ item.vector)
                if sim > best_sim:
                    best, best_sim = cluster, sim
            if best is not None and best_sim >= threshold:
                best["members"].append((item, best_sim))
                weights = np.array([m.weight for m, _ in best["members"]], dtype=np.float32)
                vecs = np.vstack([m.vector for m, _ in best["members"]])
                centroid = (vecs * weights[:, None]).sum(axis=0)
                best["centroid"] = centroid / (np.linalg.norm(centroid) or 1.0)
            else:
                clusters.append({"centroid": item.vector, "members": [(item, 1.0)]})

        open_issues = db.scalars(select(EmergingIssue).where(EmergingIssue.status.in_(("NEW", "UNDER_REVIEW")))).all()
        created = updated = 0
        touched: set[str] = set()
        for cluster in clusters:
            members = cluster["members"]
            occurrences = sum(m.weight for m, _ in members)
            if occurrences < s.emerging_min_cluster_size:
                continue
            centroid = cluster["centroid"]
            match = None
            for issue in open_issues:
                if issue.id in touched or issue.centroid is None or len(issue.centroid) != len(centroid):
                    continue
                if float(np.asarray(issue.centroid) @ centroid) >= threshold:
                    match = issue
                    break
            keywords = self._keywords([(m.complaint, m.weight) for m, _ in members])
            avg_evidence = sum(m.evidence_score * m.weight for m, _ in members) / occurrences
            category = Counter({m.category: 0 for m, _ in members})
            for m, _ in members:
                category[m.category] += m.weight
            top_category = category.most_common(1)[0][0] if category else "Unclassified"
            examples = list(dict.fromkeys(m.complaint for m, _ in sorted(members, key=lambda x: -x[1])))[:5]
            pattern = " · ".join(k.title() for k in keywords[:3]) or "Unlabelled pattern"
            suggested = re.sub(r"[^a-z0-9_]", "", "_".join(keywords[:2]))[:60] or "new_issue"
            if match is None:
                match = EmergingIssue(id=short_id("EMG"), status="NEW")
                db.add(match)
                created += 1
            else:
                updated += 1
                db.execute(delete(EmergingIssueMember).where(EmergingIssueMember.emerging_issue_id == match.id))
            touched.add(match.id)
            match.pattern_name = pattern
            match.description = (f"{occurrences} unresolved complaint(s) share this pattern; average evidence score "
                                 f"{avg_evidence:.2f}. Requires human review before any intent is created.")
            match.occurrences = occurrences
            match.avg_evidence_score = avg_evidence
            match.keywords = keywords
            match.example_complaints = examples
            match.suggested_intent_name = suggested
            match.suggested_category = top_category
            match.centroid = centroid
            match.updated_at = utcnow()
            db.flush()
            for item, sim in members:
                db.add(EmergingIssueMember(emerging_issue_id=match.id, member_type=item.member_type,
                                           member_id=item.member_id, complaint=item.complaint, similarity=sim,
                                           evidence_score=item.evidence_score, weight=item.weight))
        db.flush()
        return {"pool_size": len(pool), "clusters": len(clusters), "created": created, "updated": updated}

    def list(self, db: Session, status: str | None = None) -> list[dict]:
        stmt = select(EmergingIssue)
        if status:
            stmt = stmt.where(EmergingIssue.status == status.upper())
        rows = db.scalars(stmt.order_by(EmergingIssue.occurrences.desc())).all()
        return [issue_to_dict(r) for r in rows]

    def get(self, db: Session, issue_id: str) -> dict:
        issue = db.get(EmergingIssue, issue_id)
        if issue is None:
            raise NotFoundError(f"Emerging issue {issue_id} not found")
        members = db.scalars(select(EmergingIssueMember).where(EmergingIssueMember.emerging_issue_id == issue_id)
                             .order_by(EmergingIssueMember.similarity.desc())).all()
        return issue_to_dict(issue, members)

    def update_status(self, db: Session, issue_id: str, status: str, notes: str | None) -> dict:
        issue = db.get(EmergingIssue, issue_id)
        if issue is None:
            raise NotFoundError(f"Emerging issue {issue_id} not found")
        status = status.upper()
        if status not in ("NEW", "UNDER_REVIEW", "REJECTED"):
            raise ValidationFailed("Status can be set to NEW, UNDER_REVIEW or REJECTED; use create-intent to approve")
        if issue.status == "APPROVED":
            raise ConflictError("Approved issues cannot change status")
        issue.status = status
        issue.review_notes = notes
        db.flush()
        return self.get(db, issue_id)
