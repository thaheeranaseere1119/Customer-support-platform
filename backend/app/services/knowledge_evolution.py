"""Knowledge base management and human-verified knowledge evolution.

Customer feedback -> CandidateCase (pending_review) -> human APPROVE -> ACTIVE KB
article -> chunked + embedded -> vector index updated.  REJECT keeps it out of
trusted knowledge. Nothing is promoted automatically.
"""
from __future__ import annotations

import csv
import json
import re
import threading
from collections import Counter
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CandidateCase, ConversationMessage, DocumentChunk, KnowledgeArticle, SupportCase, Ticket
from app.models._common import utcnow
from app.services import handoff
from app.services.embeddings import EmbeddingService
from app.services.retrieval import RetrievalService
from app.services.taxonomy import taxonomy_service
from app.utils.errors import ConflictError, NotFoundError, ValidationFailed
from app.utils.logging import log_event, short_id
from app.utils.text import strip_synthetic_tag, text_hash, truncate

GENERAL_KB_SOURCE = "synthetic_demo_kb_general"
# General checklists are generic, so they carry low quality: they can guide an unseen issue
# but never make it look like a verified, issue-specific match.
KB_SOURCE_QUALITY = {"synthetic_demo_kb": 1.0, "human_verified_candidate": 0.95, "admin_authored": 1.0,
                     "emerging_issue_review": 0.95, GENERAL_KB_SOURCE: 0.5}
TICKET_SOURCE_QUALITY = 0.85


# ------------------------------------------------------------------ dataset learning
# Live queries that a human reviewer approves are appended to the dataset CSV (same columns as the
# original 60K file) and indexed as solved tickets, so the next similar query is answered from them.
_DATASET_LOCK = threading.Lock()
LIVE_ORIGINS = ("live_feedback", "kb_match", "agent_resolved")
_EVIDENCE_TO_DATASET = {"known": "sufficient", "uncertain": "uncertain", "unknown": "insufficient"}
_SEVERITIES = {"low", "medium", "high", "critical"}
_SENTIMENTS = {"positive", "neutral", "negative", "frustrated", "urgent"}


ALSO_ASKED = "Also asked as:"
ARTICLE_CHUNK_CHARS = 2400  # help articles are indexed whole (agent and customer steps together)
MAX_ALSO_ASKED = 12  # most recent customer phrasings kept on one article


def _resolution_section(body: str) -> str:
    """The "Resolution steps:" part of an article body (what the reviewer approved), if present."""
    match = re.search(r"Resolution steps:\s*\n(.*?)(?:\n\s*(?:Customer steps|Escalate when|Caution|Source note):|\Z)",
                      body or "", re.S)
    return match.group(1).strip() if match else ""


def is_dataset_query(db: Session, complaint: str) -> bool:
    """True when the complaint is (verbatim) a ticket already in the dataset, i.e. not a new query."""
    text = (complaint or "").strip().lower()
    if not text:
        return False
    return db.scalar(select(Ticket.record_id).where(or_(
        func.lower(Ticket.customer_complaint) == text,
        func.lower(Ticket.customer_complaint).startswith(f"{text} [synthetic", autoescape=True))).limit(1)) is not None


def _dataset_split_for(db: Session, intent: str) -> str:
    # Splits are intent-disjoint: a new row joins whichever split its intent already belongs to.
    splits = Counter(db.scalars(select(Ticket.dataset_split).where(Ticket.intent == intent).limit(500)).all())
    return splits.most_common(1)[0][0] if splits else "development"


def _append_csv_row(path: Path, row: dict) -> None:
    with _DATASET_LOCK:
        with path.open("r", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        with path.open("rb") as fh:
            fh.seek(0, 2)
            needs_newline = fh.tell() > 0 and (fh.seek(-1, 2) or fh.read(1)) not in (b"\n", b"\r")
        with path.open("a", encoding="utf-8", newline="") as fh:
            if needs_newline:
                fh.write("\r\n")
            csv.DictWriter(fh, fieldnames=header, extrasaction="ignore").writerow({h: row.get(h, "") for h in header})


def candidate_from_agent_fix(db: Session, case: SupportCase, agent: str) -> CandidateCase | None:
    """Turn an agent-solved case into candidate knowledge (pending human review).

    The proposed resolution is what the agent told the customer after the case was opened. Nothing is
    queued when the agent wrote nothing, or when the case already has a candidate.
    """
    if db.scalar(select(CandidateCase).where(CandidateCase.case_id == case.id)):
        return None
    stmt = select(ConversationMessage).where(ConversationMessage.session_id == case.session_id,
                                             ConversationMessage.role == "agent",
                                             ConversationMessage.created_at >= case.created_at)
    next_case = db.scalar(select(func.min(SupportCase.created_at)).where(SupportCase.session_id == case.session_id,
                                                                          SupportCase.created_at > case.created_at))
    if next_case is not None:
        stmt = stmt.where(ConversationMessage.created_at < next_case)
    replies = db.scalars(stmt.order_by(ConversationMessage.id)).all()
    steps = [m.message.strip() for m in replies if m.message.strip()]
    if not steps:
        return None
    candidate = CandidateCase(
        id=short_id("CAND"), case_id=case.id, origin="agent_resolved", complaint=case.complaint,
        intent=case.intent, category=case.category, product=case.product,
        proposed_title=truncate(f"{case.analysis.get('intent_display', 'New issue')}: {case.complaint}", 190),
        proposed_resolution="\n".join(f"{i}. {text}" for i, text in enumerate(steps, 1)),
        sources=[], evidence_score=case.evidence_score, attempt_number=case.current_attempt,
        customer_feedback="solved_by_agent", occurrences=1, emerging_signal=case.evidence_status == "unknown",
        status="pending_review", embedding=case.embedding, embedding_model=case.embedding_model,
    )
    db.add(candidate)
    db.flush()
    log_event("candidate_from_agent", db=db, session_id=case.session_id, case_id=case.id, candidate_id=candidate.id, agent=agent)
    return candidate


def chunk_text(content: str, max_chars: int = 900) -> list[str]:
    lines = [ln for ln in (content or "").splitlines() if ln.strip()]
    chunks, current = [], ""
    for line in lines:
        if current and len(current) + len(line) + 1 > max_chars:
            chunks.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks or [content or ""]


def article_to_dict(article: KnowledgeArticle) -> dict:
    return {
        "id": article.id, "article_id": article.article_id, "version": article.version, "title": article.title,
        "content": article.content, "category": article.category, "intent": article.intent, "product": article.product,
        "status": article.status, "source": article.source, "source_type": article.source_type,
        "created_by": article.created_by, "change_note": article.change_note, "is_latest": article.is_latest,
        "created_at": article.created_at.isoformat() if article.created_at else None,
        "updated_at": article.updated_at.isoformat() if article.updated_at else None,
    }


def candidate_to_dict(c: CandidateCase) -> dict:
    return {
        "id": c.id, "case_id": c.case_id, "origin": c.origin, "complaint": c.complaint, "intent": c.intent,
        "category": c.category, "product": c.product, "proposed_title": c.proposed_title,
        "proposed_resolution": c.proposed_resolution, "sources": c.sources, "evidence_score": round(c.evidence_score, 4),
        "attempt_number": c.attempt_number, "customer_feedback": c.customer_feedback, "occurrences": c.occurrences,
        "emerging_signal": c.emerging_signal, "status": c.status, "reviewer": c.reviewer, "review_notes": c.review_notes,
        "approved_article_id": c.approved_article_id, "dataset_record_ids": list(c.dataset_record_ids or []),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
    }


class KnowledgeService:
    def __init__(self, embeddings: EmbeddingService, retrieval: RetrievalService):
        self.embeddings = embeddings
        self.retrieval = retrieval

    # ------------------------------------------------------------- indexing
    def index_article(self, db: Session, article: KnowledgeArticle) -> int:
        """(Re)build the chunks of an article; only ACTIVE articles become retrievable."""
        for chunk in db.scalars(select(DocumentChunk).where(DocumentChunk.source_type == "knowledge_base",
                                                            DocumentChunk.source_id == article.article_id)):
            chunk.is_active = False
        db.flush()
        created = 0
        if article.status == "ACTIVE" and article.is_latest:
            taxonomy = taxonomy_service.get(db)
            intent = taxonomy.intents.get(article.intent)
            pieces = chunk_text(article.content, max_chars=ARTICLE_CHUNK_CHARS)  # one chunk keeps both step lists
            vectors = self.embeddings.embed([f"{article.title}. {p}" for p in pieces])
            for idx, (piece, vec) in enumerate(zip(pieces, vectors)):
                chunk_id = f"{article.article_id}:v{article.version}:{idx}"
                existing = db.scalar(select(DocumentChunk).where(DocumentChunk.chunk_id == chunk_id))
                chunk = existing or DocumentChunk(chunk_id=chunk_id)
                chunk.source_type = "knowledge_base"
                chunk.source_id = article.article_id
                chunk.source_version = article.version
                chunk.article_pk = article.id
                chunk.title = f"{article.article_id}: {article.title}"
                chunk.content = piece
                chunk.intent = article.intent
                chunk.category = article.category
                chunk.domain_category = intent.domain_category if intent else ""
                chunk.product = article.product or ""
                chunk.quality = KB_SOURCE_QUALITY.get(article.source, 0.9)
                chunk.is_active = True
                chunk.extra = {"status": article.status, "version": article.version, "source": article.source,
                               "general": article.source == GENERAL_KB_SOURCE}
                chunk.text_hash = text_hash(piece)
                chunk.embedding = vec
                chunk.embedding_model = self.embeddings.model_id
                if existing is None:
                    db.add(chunk)
                created += 1
        db.flush()
        self.retrieval.mark_dirty()
        return created

    # ---------------------------------------------------------------- CRUD
    def next_article_id(self, db: Session) -> str:
        ids = db.scalars(select(KnowledgeArticle.article_id).distinct()).all()
        numbers = [int(m.group(1)) for a in ids if (m := re.match(r"KB-(\d+)$", a))]
        return f"KB-{(max(numbers) + 1 if numbers else 1):03d}"

    def latest(self, db: Session, article_id: str) -> KnowledgeArticle:
        article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.article_id == article_id,
                                                           KnowledgeArticle.is_latest.is_(True)))
        if article is None:
            raise NotFoundError(f"Knowledge article {article_id} not found")
        return article

    def list_articles(self, db: Session, *, status: str | None, category: str | None, intent: str | None,
                      q: str | None, page: int, page_size: int) -> tuple[list[dict], int]:
        stmt = select(KnowledgeArticle).where(KnowledgeArticle.is_latest.is_(True))
        if status:
            stmt = stmt.where(KnowledgeArticle.status == status.upper())
        if category:
            stmt = stmt.where(KnowledgeArticle.category.in_(taxonomy_service.get(db).categories_under(category)))
        if intent:
            stmt = stmt.where(KnowledgeArticle.intent == intent)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(KnowledgeArticle.title).like(like), func.lower(KnowledgeArticle.content).like(like),
                                  func.lower(KnowledgeArticle.article_id).like(like)))
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.scalars(stmt.order_by(KnowledgeArticle.article_id).offset((page - 1) * page_size).limit(page_size)).all()
        return [article_to_dict(a) for a in rows], total

    def get_article(self, db: Session, article_id: str) -> dict:
        latest = self.latest(db, article_id)
        versions = db.scalars(select(KnowledgeArticle).where(KnowledgeArticle.article_id == article_id)
                              .order_by(KnowledgeArticle.version.desc())).all()
        chunks = db.scalar(select(func.count()).select_from(DocumentChunk).where(
            DocumentChunk.source_id == article_id, DocumentChunk.is_active.is_(True))) or 0
        data = article_to_dict(latest)
        data["versions"] = [article_to_dict(v) for v in versions]
        data["indexed_chunks"] = chunks
        return data

    def _validate_fields(self, db: Session, category: str, intent: str) -> None:
        taxonomy = taxonomy_service.get(db)
        if category not in taxonomy.categories and category != "Unclassified":
            raise ValidationFailed(f"Unknown category '{category}'")
        if intent not in taxonomy.intents and intent != "unknown":
            raise ValidationFailed(f"Unknown intent '{intent}'")

    def create_article(self, db: Session, *, title: str, content: str, category: str, intent: str, product: str = "",
                       status: str = "ACTIVE", source: str = "admin_authored", created_by: str = "admin",
                       article_id: str | None = None) -> KnowledgeArticle:
        self._validate_fields(db, category, intent)
        article_id = article_id or self.next_article_id(db)
        if db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.article_id == article_id)):
            raise ConflictError(f"Article {article_id} already exists")
        article = KnowledgeArticle(article_id=article_id, version=1, is_latest=True, title=title.strip(),
                                   content=content.strip(), category=category, intent=intent, product=product,
                                   status=status.upper(), source=source, source_type="knowledge_article",
                                   created_by=created_by, change_note="created")
        db.add(article)
        db.flush()
        self.index_article(db, article)
        return article

    def update_article(self, db: Session, article_id: str, changes: dict, editor: str = "admin") -> KnowledgeArticle:
        """Never edits in place: creates a new version and archives the previous one."""
        current = self.latest(db, article_id)
        values = {k: changes[k] for k in ("title", "content", "category", "intent", "product", "status")
                  if changes.get(k) is not None}
        if not values:
            raise ValidationFailed("No changes supplied")
        self._validate_fields(db, values.get("category", current.category), values.get("intent", current.intent))
        current.is_latest = False
        previous_status = current.status
        if current.status == "ACTIVE":
            current.status = "ARCHIVED"
        new = KnowledgeArticle(
            article_id=current.article_id, version=current.version + 1, is_latest=True,
            title=values.get("title", current.title), content=values.get("content", current.content),
            category=values.get("category", current.category), intent=values.get("intent", current.intent),
            product=values.get("product", current.product), status=str(values.get("status", previous_status)).upper(),
            source=current.source, source_type=current.source_type, created_by=editor,
            change_note=changes.get("change_note") or f"updated from v{current.version}",
        )
        db.add(new)
        db.flush()
        self.index_article(db, new)
        return new

    # ----------------------------------------------------- candidate workflow
    def create_candidate_from_case(self, db: Session, case: SupportCase, attempt, feedback_outcome: str,
                                  origin: str = "live_feedback") -> CandidateCase:
        existing = db.scalar(select(CandidateCase).where(CandidateCase.case_id == case.id,
                                                         CandidateCase.status == "pending_review"))
        if existing:
            return existing
        steps = [s for s in attempt.steps if s.get("kind") == "resolution"] or attempt.steps
        resolution = "\n".join(f"{i}. {s['text']}" for i, s in enumerate(steps, 1))
        candidate = CandidateCase(
            id=short_id("CAND"), case_id=case.id, origin=origin, complaint=case.complaint,
            intent=case.intent, category=case.category, product=case.product,
            proposed_title=truncate(f"{case.analysis.get('intent_display', 'New issue')}: {case.complaint}", 190),
            proposed_resolution=resolution, sources=[{"source_id": c["source_id"], "source_type": c["source_type"],
                                                      "title": c["title"], "score": c["score"]} for c in attempt.citations],
            evidence_score=attempt.evidence_score, attempt_number=attempt.attempt_number,
            customer_feedback=feedback_outcome, occurrences=1, emerging_signal=case.evidence_status == "unknown",
            status="pending_review", embedding=case.embedding, embedding_model=case.embedding_model,
        )
        db.add(candidate)
        db.flush()
        return candidate

    def create_candidate_from_agent_fix(self, db: Session, case: SupportCase, agent: str) -> CandidateCase | None:
        """A human agent solved a case the assistant could not: queue the agent's replies for review."""
        return candidate_from_agent_fix(db, case, agent)

    def list_candidates(self, db: Session, *, status: str | None, origin: str | None, page: int, page_size: int) -> tuple[list[dict], int]:
        stmt = select(CandidateCase)
        if status:
            stmt = stmt.where(CandidateCase.status == status)
        if origin:
            stmt = stmt.where(CandidateCase.origin == origin)
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.scalars(stmt.order_by(CandidateCase.created_at.desc(), CandidateCase.id)
                          .offset((page - 1) * page_size).limit(page_size)).all()
        return [candidate_to_dict(c) for c in rows], total

    def approve(self, db: Session, item_id: str, *, reviewer: str, notes: str | None, title: str | None = None,
                content: str | None = None, intent: str | None = None, category: str | None = None) -> dict:
        if item_id.upper().startswith("CAND"):
            candidate = db.get(CandidateCase, item_id)
            if candidate is None:
                raise NotFoundError(f"Candidate {item_id} not found")
            if candidate.status != "pending_review":
                raise ConflictError(f"Candidate {item_id} is already {candidate.status}")
            taxonomy = taxonomy_service.get(db)
            final_intent = intent or candidate.intent
            final_category = category or (taxonomy.intents[final_intent].support_category
                                          if final_intent in taxonomy.intents else candidate.category)
            if final_category not in taxonomy.categories:
                final_category = "Unclassified"
            steps = re.sub(r"\s*\[[^\]]+\]", "", candidate.proposed_resolution).strip()
            body = content or (
                f"Symptoms: {strip_synthetic_tag(candidate.complaint)}\nResolution steps:\n{steps}\n"
                f"Escalate when: The steps above do not resolve the issue.\n"
                f"Caution: Human-verified from candidate {candidate.id}"
                f"{' (case ' + candidate.case_id + ')' if candidate.case_id else ''}; customer feedback was "
                f"'{candidate.customer_feedback}'.\nSource note: verified by {reviewer}."
            )
            # A query solved by an existing verified article adds the customer's wording to that article (and a
            # dataset example), not a duplicate article.
            kb_match = candidate.origin == "kb_match"
            article = None if kb_match else self.create_article(
                db, title=title or truncate(candidate.proposed_title, 190), content=body, category=final_category,
                intent=final_intent, product=candidate.product or "", status="ACTIVE",
                source="human_verified_candidate", created_by=reviewer)
            candidate.status = "approved"
            candidate.reviewer = reviewer
            candidate.review_notes = notes
            candidate.reviewed_at = utcnow()
            if article is not None:
                candidate.approved_article_id = article.article_id
            cited = next((x["source_id"] for x in candidate.sources if x.get("source_type") == "knowledge_base"), None)
            updated = self._add_customer_wording(db, cited, candidate, reviewer) if kb_match else None
            if updated is not None:
                candidate.approved_article_id = updated.article_id
            record_id = self.add_to_dataset(db, candidate, intent=final_intent, resolution=_resolution_section(body) or steps,
                                            reviewer=reviewer,
                                            citation_id=article.article_id if article else (cited or "human_review"))
            if article is not None and candidate.case_id:
                case = db.get(SupportCase, candidate.case_id)
                handoff.notify(db, case.session_id if case else None,
                               f"Update on your issue: a support specialist verified the fix "
                               f"{'our agent gave you' if candidate.origin == 'agent_resolved' else 'you confirmed'} and added it "
                               f"to our knowledge base as {article.article_id}, so future customers get it straight away. Thank you!",
                               {"candidate_id": candidate.id, "article_id": article.article_id, "review": "approved"})
            if updated is not None and candidate.case_id:
                case = db.get(SupportCase, candidate.case_id)
                handoff.notify(db, case.session_id if case else None,
                               f"Update on your issue: a support specialist confirmed the fix that worked for you and "
                               f"added your question to help article {updated.article_id}, so customers who describe it "
                               f"the same way get it straight away. Thank you!",
                               {"candidate_id": candidate.id, "article_id": updated.article_id, "review": "approved"})
            db.flush()
            return {"item_id": item_id, "status": "approved", "article": article_to_dict(article) if article else None,
                    "updated_article": article_to_dict(updated) if updated else None,
                    "indexed": True, "index_version_pending": True, "dataset_record_id": record_id}
        article = self.latest(db, item_id)
        if article.status != "DRAFT":
            raise ConflictError(f"Only DRAFT articles can be approved (current status {article.status})")
        article.status = "ACTIVE"
        article.change_note = f"approved by {reviewer}" + (f": {notes}" if notes else "")
        db.flush()
        self.index_article(db, article)
        return {"item_id": item_id, "status": "approved", "article": article_to_dict(article), "indexed": True,
                "index_version_pending": True}

    def _add_customer_wording(self, db: Session, article_id: str | None, candidate: CandidateCase,
                              reviewer: str) -> KnowledgeArticle | None:
        """Save a new way of describing the problem on the article that solved it (as a new version).

        The "Also asked as:" line is searched like the rest of the article, so the next customer who words the
        problem the same way finds it; it is not a numbered step, so it never becomes part of an answer.
        """
        if not article_id:
            return None
        current = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.article_id == article_id,
                                                           KnowledgeArticle.is_latest.is_(True)))
        if current is None or current.status != "ACTIVE":
            return None
        phrase = truncate(re.sub(r"\s+", " ", strip_synthetic_tag(candidate.complaint)).strip(" |"), 200)
        lines = (current.content or "").splitlines()
        index = next((i for i, line in enumerate(lines) if line.startswith(ALSO_ASKED)), None)
        known = [p.strip() for p in lines[index][len(ALSO_ASKED):].split("|")] if index is not None else []
        if not phrase or phrase.lower() in {k.lower() for k in known}:
            return current
        line = ALSO_ASKED + " " + " | ".join((known + [phrase])[-MAX_ALSO_ASKED:])
        if index is not None:
            lines[index] = line
        else:  # right after "Symptoms:", so it stays out of the "Resolution steps" section
            at = next((i + 1 for i, text in enumerate(lines) if text.startswith("Symptoms:")), 0)
            lines.insert(at, line)
        return self.update_article(db, article_id, {"content": "\n".join(lines),
                                                    "change_note": f"added customer wording from {candidate.id}"},
                                   editor=reviewer)

    def add_to_dataset(self, db: Session, candidate: CandidateCase, *, intent: str, resolution: str, reviewer: str,
                       citation_id: str) -> str | None:
        """Append an approved live query to the dataset CSV and the tickets table, and index it for retrieval."""
        if not candidate.case_id or candidate.origin not in LIVE_ORIGINS:
            return None  # dataset- and seed-derived candidates are already in the dataset
        taxonomy = taxonomy_service.get(db)
        info = taxonomy.intents.get(intent)
        if info is None or not resolution.strip():
            log_event("dataset_append_skipped", db=db, case_id=candidate.case_id, reason=f"intent {intent!r} not in taxonomy")
            return None
        case = db.get(SupportCase, candidate.case_id)
        suffix = candidate.id.split("-", 1)[-1]
        record_id, ticket_id = f"TELCO-LIVE-{suffix}", f"LIVE-TKT-{suffix}"
        if db.get(Ticket, record_id):
            return record_id
        analysis = (case.analysis if case else {}) or {}
        entities = {e["type"]: e["value"] for e in analysis.get("entities", []) if isinstance(e, dict) and "type" in e and "value" in e}
        complaint = strip_synthetic_tag(candidate.complaint)
        product = candidate.product or info.default_product or "general"
        split = _dataset_split_for(db, intent)
        resolution_line = " ".join(re.sub(r"^\d+\.\s*", "", ln).strip() for ln in resolution.splitlines() if ln.strip())
        severity = case.severity if case and case.severity in _SEVERITIES else "medium"
        sentiment = case.sentiment if case and case.sentiment in _SENTIMENTS else "neutral"
        now = utcnow()
        values = {
            "record_id": record_id, "ticket_id": ticket_id, "customer_id": "", "dataset_split": split,
            "customer_complaint": complaint, "category": info.domain_category, "intent": intent, "product": product,
            "severity": severity, "sentiment": sentiment, "language": "en",
            "interaction_mode": (case.input_mode if case else "free_text") or "free_text", "channel": "customer_app",
            "conversation_context": f"Product={product}; intent={intent}; channel=customer_app; source=live chat",
            "previous_troubleshooting": "Not stated",
            "retrieval_text": f"{complaint} | {info.domain_category} | {intent} | {product}",
            "resolution": resolution_line, "resolution_attempt": candidate.attempt_number or 1,
            "resolution_status": "resolved",
            "evidence_status": _EVIDENCE_TO_DATASET.get(case.evidence_status if case else "", "uncertain"),
            "evidence_score": round(float(candidate.evidence_score or 0.0), 2), "citation_source_id": citation_id,
            "citation_type": "knowledge_base", "customer_feedback": candidate.customer_feedback,
            "human_verification_status": "human_verified", "knowledge_state": "trusted",
            "emerging_class_signal": "emerging_candidate" if candidate.emerging_signal else "none",
            "escalation_required": "yes" if case and case.escalated else "no",
            "source": "live_agent_chat" if candidate.origin == "agent_resolved" else "live_customer_chat",
            "source_type": "human_verified_live_ticket",
        }
        db.add(Ticket(**{k: v for k, v in values.items() if k not in ("customer_id", "escalation_required")},
                      customer_id=None, escalation_required=values["escalation_required"] == "yes", entities=entities,
                      created_at=now))
        if split == "development":  # calibration / held-out intents stay out of the retrieval index
            content = f"Complaint: {complaint}\nResolution: {resolution_line}\nPrevious troubleshooting: Not stated"
            db.add(DocumentChunk(
                chunk_id=f"TKT:{ticket_id}", source_type="historical_ticket", source_id=ticket_id,
                title=f"Ticket {ticket_id}: {info.display_name}", content=content, intent=intent,
                category=info.support_category, domain_category=info.domain_category, product=product,
                quality=TICKET_SOURCE_QUALITY, is_active=True, text_hash=text_hash(content),
                extra={"ticket_ids": [ticket_id], "duplicate_count": 1, "dataset_split": split,
                       "kb_reference": citation_id, "source": values["source"], "domain_category": info.domain_category},
                embedding=self.embeddings.embed([content])[0], embedding_model=self.embeddings.model_id))
            self.retrieval.mark_dirty()
        candidate.dataset_record_ids = [*(candidate.dataset_record_ids or []), record_id]
        db.flush()
        path = Path(get_settings().dataset_path)
        if path.exists():
            _append_csv_row(path, {**values, "entities_json": json.dumps(entities),
                                   "created_at": now.strftime("%d/%m/%y")})
        log_event("dataset_row_added", db=db, case_id=candidate.case_id, record_id=record_id, split=split,
                  reviewer=reviewer, path=str(path))
        return record_id

    def reject(self, db: Session, item_id: str, *, reviewer: str, notes: str | None) -> dict:
        if item_id.upper().startswith("CAND"):
            candidate = db.get(CandidateCase, item_id)
            if candidate is None:
                raise NotFoundError(f"Candidate {item_id} not found")
            if candidate.status != "pending_review":
                raise ConflictError(f"Candidate {item_id} is already {candidate.status}")
            candidate.status = "rejected"
            candidate.reviewer = reviewer
            candidate.review_notes = notes
            candidate.reviewed_at = utcnow()
            if candidate.case_id and candidate.origin != "kb_match":
                case = db.get(SupportCase, candidate.case_id)
                handoff.notify(db, case.session_id if case else None,
                               "Update on your issue: thanks for confirming those steps. A support specialist has reviewed them, "
                               "and if anything comes up again, just message us here.",
                               {"candidate_id": candidate.id, "review": "rejected"})
            db.flush()
            return {"item_id": item_id, "status": "rejected", "article": None, "indexed": False}
        article = self.latest(db, item_id)
        if article.status != "DRAFT":
            raise ConflictError(f"Only DRAFT articles can be rejected (current status {article.status})")
        article.status = "ARCHIVED"
        article.change_note = f"rejected by {reviewer}" + (f": {notes}" if notes else "")
        db.flush()
        self.index_article(db, article)
        return {"item_id": item_id, "status": "rejected", "article": article_to_dict(article), "indexed": False}
