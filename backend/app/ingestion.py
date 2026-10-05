"""Data ingestion: validate -> normalise -> insert tickets / KB / candidates -> chunk ->
embed -> build index. Used by scripts/ingest_data.py and first-run auto-seeding."""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.config import DATA_DIR, get_settings
from app.database import Base, create_all, get_engine, session_scope
from app.models import (
    CandidateCase,
    DocumentChunk,
    IntentTaxonomy,
    KnowledgeArticle,
    ProductCatalog,
    SupportCategory,
    Ticket,
)
from app.models._common import utcnow
from app.services.embeddings import EmbeddingService, get_embedding_service
from app.services.knowledge_evolution import TICKET_SOURCE_QUALITY, KnowledgeService
from app.services.retrieval import RetrievalService
from app.services.taxonomy import taxonomy_service
from app.utils.logging import short_id
from app.utils.text import strip_synthetic_tag, text_hash, truncate
from app.utils.validation import (
    parse_timestamp,
    read_csv_rows,
    validate_rows,
    write_rejections,
)

logger = logging.getLogger(__name__)


def _split(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split("|") if v.strip()]


# Too general: they matched unrelated questions ("not active" pulled SIM questions into service activation;
# "your network" and "arrived in" shrink to one common word once stop-words are dropped).
RETIRED_KEYWORDS = {"on and off", "off and on", "not active", "not activated", "data plans", "your network", "arrived in"}


def sync_intent_keywords(db: Session) -> int:
    """Add new keywords and example complaints from intent_taxonomy.csv to issue types already in the database.

    Additions only, except seed keywords that were withdrawn from the file (RETIRED_KEYWORDS) are removed."""
    _, rows = read_csv_rows(DATA_DIR / "intent_taxonomy.csv")
    changed = 0
    for row in rows:
        intent = db.scalar(select(IntentTaxonomy).where(IntentTaxonomy.name == row["name"]))
        if intent is None:
            continue
        keywords = [k for k in (intent.keywords or []) if k not in RETIRED_KEYWORDS]
        keywords += [k for k in _split(row["keywords"]) if k not in keywords]
        examples = list(intent.example_complaints or [])
        examples += [e for e in _split(row["example_complaints"]) if e not in examples]
        if keywords != (intent.keywords or []) or examples != (intent.example_complaints or []):
            intent.keywords, intent.example_complaints = keywords, examples
            changed += 1
    if changed:
        from app.services.taxonomy import taxonomy_service
        taxonomy_service.invalidate()
    return changed


def sync_products(db: Session) -> int:
    """Insert missing products and add new keywords from products.csv to existing ones (keywords are only added)."""
    created = 0
    _, rows = read_csv_rows(DATA_DIR / "products.csv")
    for row in rows:
        keywords = _split(row["keywords"])
        product = db.scalar(select(ProductCatalog).where(ProductCatalog.name == row["name"]))
        if product is None:
            db.add(ProductCatalog(name=row["name"], support_category=row["support_category"], keywords=keywords))
            created += 1
        elif missing := [k for k in keywords if k not in (product.keywords or [])]:
            product.keywords = list(product.keywords or []) + missing
    return created


def seed_taxonomy(db: Session) -> dict:
    created = {"categories": 0, "products": 0, "intents": 0}
    _, rows = read_csv_rows(DATA_DIR / "support_categories.csv")
    for row in rows:
        if db.scalar(select(SupportCategory).where(SupportCategory.name == row["name"])) is None:
            db.add(SupportCategory(name=row["name"], parent_name=row["parent_name"] or None, icon=row["icon"],
                                   description=row["description"], sort_order=int(row["sort_order"])))
            created["categories"] += 1
    created["products"] = sync_products(db)
    _, rows = read_csv_rows(DATA_DIR / "intent_taxonomy.csv")
    for row in rows:
        if db.scalar(select(IntentTaxonomy).where(IntentTaxonomy.name == row["name"])) is None:
            db.add(IntentTaxonomy(name=row["name"], display_name=row["display_name"], description=row["description"],
                                  domain_category=row["domain_category"], support_category=row["support_category"],
                                  default_product=row["default_product"] or None, keywords=_split(row["keywords"]),
                                  example_complaints=_split(row["example_complaints"]),
                                  clarifying_question=row["clarifying_question"] or None, origin="dataset"))
            created["intents"] += 1
    db.commit()
    taxonomy_service.invalidate()
    return created


def ingest_tickets(db: Session, path: Path, *, strict: bool = False, reject_path: Path | None = None,
                   only_prefix: str | None = None) -> dict:
    columns, rows = read_csv_rows(path)
    if only_prefix:
        rows = [r for r in rows if (r.get("record_id") or "").startswith(only_prefix)]
    taxonomy = taxonomy_service.get(db)
    existing_records = set(db.scalars(select(Ticket.record_id)).all())
    existing_tickets = set(db.scalars(select(Ticket.ticket_id)).all())
    fresh = [r for r in rows if (r.get("record_id") or "").strip() not in existing_records]
    skipped_existing = len(rows) - len(fresh)
    report = validate_rows(fresh, valid_intents=set(taxonomy.intents), valid_categories=taxonomy.domain_categories,
                           existing_ticket_ids=existing_tickets, columns=columns)
    summary = report.summary()
    summary["skipped_already_ingested"] = skipped_existing
    if report.rejected and reject_path:
        write_rejections(report, reject_path)
        summary["rejections_file"] = str(reject_path)
    if report.missing_columns:
        raise ValueError(f"Dataset {path} is missing required columns: {report.missing_columns}")
    if strict and report.rejected:
        raise ValueError(f"{len(report.rejected)} malformed rows rejected (strict mode); see {reject_path}")
    batch: list[dict] = []
    for row in report.valid_rows:
        batch.append({
            "record_id": row["record_id"], "ticket_id": row["ticket_id"], "customer_id": row.get("customer_id") or None,
            "dataset_split": row["dataset_split"], "customer_complaint": row["customer_complaint"],
            "category": row["category"], "intent": row["intent"], "product": row["product"], "severity": row["severity"],
            "sentiment": row["sentiment"], "language": row.get("language") or "en",
            "interaction_mode": row.get("interaction_mode") or "free_text", "channel": row.get("channel") or "web",
            "entities": row["entities_parsed"], "conversation_context": row.get("conversation_context", ""),
            "previous_troubleshooting": row.get("previous_troubleshooting", ""), "retrieval_text": row["retrieval_text"],
            "resolution": row["resolution"], "resolution_attempt": row["resolution_attempt_parsed"],
            "resolution_status": row["resolution_status"], "evidence_status": row["evidence_status"],
            "evidence_score": row["evidence_score_parsed"], "citation_source_id": row["citation_source_id"],
            "citation_type": row["citation_type"], "customer_feedback": row["customer_feedback"],
            "human_verification_status": row["human_verification_status"], "knowledge_state": row["knowledge_state"],
            "emerging_class_signal": row["emerging_class_signal"], "escalation_required": row["escalation_parsed"],
            "created_at": row["created_at_parsed"], "source": row["source"], "source_type": row["source_type"],
        })
        if len(batch) >= 5000:
            db.execute(insert(Ticket), batch)
            batch = []
    if batch:
        db.execute(insert(Ticket), batch)
    db.commit()
    summary["inserted"] = len(report.valid_rows)
    return summary


def ingest_knowledge(db: Session, knowledge: KnowledgeService, path: Path) -> dict:
    _, rows = read_csv_rows(path)
    created = skipped = 0
    for row in rows:
        version = int(row.get("version") or 1)
        if db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.article_id == row["article_id"],
                                                    KnowledgeArticle.version == version)):
            skipped += 1
            continue
        status = row["status"].upper()
        if status not in ("ACTIVE", "DRAFT", "ARCHIVED"):
            raise ValueError(f"Invalid KB status '{status}' for {row['article_id']}")
        article = KnowledgeArticle(
            article_id=row["article_id"], version=version, is_latest=True, title=row["title"], content=row["content"],
            category=row["category"], intent=row["intent"], product=row.get("product", ""), status=status,
            source=row.get("source") or "synthetic_demo_kb", source_type="synthetic_knowledge_article",
            created_by="seed", change_note="seeded (SYNTHETIC / DEMO DATA)",
            created_at=parse_timestamp(row.get("created_at", "")) or None,
        )
        db.add(article)
        db.flush()
        created += 1
    db.commit()
    return {"created": created, "skipped_existing": skipped}


def sync_seed_articles(db: Session, knowledge: KnowledgeService, path: Path) -> dict:
    """Bring existing databases up to date with the seed article file (e.g. new customer wording).

    An article still as seeded gets a new version with the file's content. An article a person has changed is left
    alone, except that its customer wording is added when its agent steps are still the seeded ones.
    """
    from app.services.grounded_templates import parse_kb

    _, rows = read_csv_rows(path)
    updated = wording_added = 0
    for row in rows:
        latest = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.article_id == row["article_id"],
                                                          KnowledgeArticle.is_latest.is_(True)))
        if latest is None or latest.content == row["content"]:
            continue
        if latest.created_by == "seed":
            knowledge.update_article(db, latest.article_id, {"content": row["content"],
                                                             "change_note": "seed update: customer wording"},
                                     editor="seed")
            updated += 1
            continue
        seeded, current = parse_kb(row["content"]), parse_kb(latest.content)
        block = re.search(r"\nCustomer steps:\n(?:\d+[.)].*(?:\n|$))+", row["content"])
        if block and not current["customer_steps"] and current["steps"] == seeded["steps"]:
            anchor = re.search(r"\n(?:Escalate when|Caution|Source note):", latest.content)
            at = anchor.start() if anchor else len(latest.content)
            content = latest.content[:at] + "\n" + block.group(0).strip("\n") + latest.content[at:]
            knowledge.update_article(db, latest.article_id, {"content": content,
                                                             "change_note": "added customer wording"},
                                     editor=latest.created_by)
            wording_added += 1
    db.commit()
    return {"updated": updated, "customer_wording_added": wording_added}


def build_ticket_chunks(db: Session) -> dict:
    """One retrievable chunk per de-duplicated complaint template of trusted, resolved
    DEVELOPMENT tickets. Calibration and held-out tickets are never indexed."""
    taxonomy = taxonomy_service.get(db)
    groups: dict[tuple[str, str], list[Ticket]] = defaultdict(list)
    stmt = select(Ticket).where(Ticket.dataset_split == "development", Ticket.knowledge_state == "trusted",
                                Ticket.resolution_status == "resolved")
    for ticket in db.scalars(stmt).yield_per(5000):
        groups[(strip_synthetic_tag(ticket.customer_complaint), ticket.intent)].append(ticket)
    existing = {c.chunk_id: c for c in db.scalars(select(DocumentChunk).where(DocumentChunk.source_type == "historical_ticket"))}
    created = updated = 0
    for (complaint, intent), tickets in groups.items():
        rep = tickets[0]
        chunk_id = f"TKT:{rep.ticket_id}"
        info = taxonomy.intents.get(intent)
        content = (f"Complaint: {complaint}\nResolution: {rep.resolution}\n"
                   f"Previous troubleshooting: {rep.previous_troubleshooting or 'Not stated'}")
        extra = {"ticket_ids": [t.ticket_id for t in tickets[:5]], "duplicate_count": len(tickets),
                 "dataset_split": "development", "kb_reference": rep.citation_source_id, "source": rep.source,
                 "domain_category": rep.category}
        chunk = existing.get(chunk_id)
        if chunk is None:
            chunk = DocumentChunk(chunk_id=chunk_id)
            db.add(chunk)
            created += 1
        else:
            updated += 1
            if chunk.text_hash != text_hash(content):
                chunk.embedding = None
                chunk.embedding_model = None
        chunk.source_type = "historical_ticket"
        chunk.source_id = rep.ticket_id
        chunk.title = f"Ticket {rep.ticket_id}: {info.display_name if info else intent}"
        chunk.content = content
        chunk.intent = intent
        chunk.category = info.support_category if info else "Unclassified"
        chunk.domain_category = rep.category
        chunk.product = rep.product
        chunk.quality = TICKET_SOURCE_QUALITY
        chunk.is_active = True
        chunk.extra = extra
        chunk.text_hash = text_hash(content)
    db.commit()
    return {"ticket_groups": len(groups), "created": created, "updated": updated}


def ingest_candidates(db: Session) -> dict:
    """Dataset candidate rows (pending human review) grouped by template + authored unseen cases."""
    taxonomy = taxonomy_service.get(db)
    if db.scalar(select(CandidateCase).where(CandidateCase.origin.in_(("dataset", "demo_seed"))).limit(1)):
        return {"created": 0, "skipped": "already seeded"}
    groups: dict[tuple[str, str], list[Ticket]] = defaultdict(list)
    for ticket in db.scalars(select(Ticket).where(Ticket.knowledge_state == "candidate",
                                                  Ticket.dataset_split == "development")).yield_per(5000):
        groups[(strip_synthetic_tag(ticket.customer_complaint), ticket.intent)].append(ticket)
    # If a trusted article for the intent was published from these candidates, the candidates are
    # recorded as already reviewed and APPROVED (linked to that article); a candidate can never be
    # "pending" for knowledge that is already trusted.
    published = {a.intent: a.article_id for a in db.scalars(select(KnowledgeArticle).where(
        KnowledgeArticle.status == "ACTIVE", KnowledgeArticle.is_latest.is_(True),
        KnowledgeArticle.source == "synthetic_demo_kb"))}
    created = 0
    for (complaint, intent), tickets in groups.items():
        rep = tickets[0]
        info = taxonomy.intents.get(intent)
        article_id = published.get(intent)
        review = ({"status": "approved", "reviewer": "seed-review", "approved_article_id": article_id,
                   "review_notes": f"Verified and published as {article_id} during seeding.", "reviewed_at": utcnow()}
                  if article_id else {"status": "pending_review"})
        db.add(CandidateCase(
            id=short_id("CAND"), origin="dataset", complaint=complaint, intent=intent,
            category=info.support_category if info else "Unclassified", product=rep.product,
            proposed_title=truncate(f"{info.display_name if info else intent}: {complaint}", 190),
            proposed_resolution=rep.resolution, sources=[], evidence_score=rep.evidence_score,
            attempt_number=rep.resolution_attempt, customer_feedback=rep.customer_feedback, occurrences=len(tickets),
            dataset_record_ids=[t.record_id for t in tickets[:10]],
            emerging_signal=any(t.emerging_class_signal == "emerging_candidate" for t in tickets), **review))
        created += 1
    authored = DATA_DIR / "candidate_cases.csv"
    if authored.exists():
        _, rows = read_csv_rows(authored)
        for row in rows:
            db.add(CandidateCase(
                id=short_id("CAND"), origin="demo_seed", complaint=row["complaint"], intent="unknown",
                category=row["category"], product="", proposed_title=truncate(f"New issue: {row['complaint']}", 190),
                proposed_resolution="No verified resolution yet. Collect device, timing and error details for review.",
                sources=[], evidence_score=0.3, attempt_number=1, customer_feedback="not_collected", occurrences=1,
                emerging_signal=True, status="pending_review"))
            created += 1
    db.commit()
    return {"created": created, "dataset_groups": len(groups)}


def embed_pending(db: Session, embeddings: EmbeddingService) -> dict:
    model_id = embeddings.model_id
    stale = db.scalars(select(DocumentChunk).where(DocumentChunk.is_active.is_(True)).where(
        (DocumentChunk.embedding_model.is_(None)) | (DocumentChunk.embedding_model != model_id))).all()
    for start in range(0, len(stale), 256):
        part = stale[start:start + 256]
        vectors = embeddings.embed([f"{c.title}. {c.content}" for c in part])
        for chunk, vec in zip(part, vectors):
            chunk.embedding = vec
            chunk.embedding_model = model_id
        db.commit()
    return {"embedded": len(stale), "model": model_id}


def reset_database() -> None:
    from app import models  # noqa: F401

    Base.metadata.drop_all(get_engine())
    create_all()


def run_ingestion(dataset: Path | None = None, *, reset: bool = False, strict: bool = False,
                  skip_embeddings: bool = False, demo_supplement: bool = True) -> dict:
    settings = get_settings()
    started = time.perf_counter()
    if reset:
        reset_database()
    else:
        create_all()
    if dataset is None:
        full = Path(settings.dataset_path)
        dataset = full if full.exists() else Path(settings.demo_dataset_path)
    if not dataset.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset}")
    summary: dict = {"dataset": str(dataset)}
    embeddings = get_embedding_service()
    retrieval = RetrievalService(embeddings)
    knowledge = KnowledgeService(embeddings, retrieval)
    with session_scope() as db:
        summary["taxonomy"] = seed_taxonomy(db)
        summary["tickets"] = ingest_tickets(db, dataset, strict=strict, reject_path=DATA_DIR / "rejected_rows.csv")
        demo = Path(settings.demo_dataset_path)
        if demo_supplement and demo.exists() and demo.resolve() != dataset.resolve():
            summary["demo_supplement"] = ingest_tickets(db, demo, strict=strict, only_prefix="DEMO-",
                                                        reject_path=DATA_DIR / "rejected_demo_rows.csv")
        summary["knowledge"] = ingest_knowledge(db, knowledge, Path(settings.knowledge_base_path))
        if not skip_embeddings:
            embeddings.load()
        chunked = 0
        for article in db.scalars(select(KnowledgeArticle).where(KnowledgeArticle.is_latest.is_(True))).all():
            if skip_embeddings:
                continue
            chunked += knowledge.index_article(db, article)
        db.commit()
        summary["knowledge"]["chunks"] = chunked
        summary["ticket_chunks"] = build_ticket_chunks(db)
        summary["candidates"] = ingest_candidates(db)
        if not skip_embeddings:
            summary["embeddings"] = embed_pending(db, embeddings)
            retrieval.ensure_index(db)
            summary["index"] = retrieval.stats()
            from app.services.emerging_issue import EmergingIssueService

            summary["emerging"] = EmergingIssueService(embeddings).detect(db)
        db.commit()
    summary["seconds"] = round(time.perf_counter() - started, 1)
    return summary


def database_is_empty() -> bool:
    with session_scope() as db:
        return db.scalar(select(Ticket.record_id).limit(1)) is None


def purge_live_data(db: Session) -> None:
    """Remove live cases/conversations (used by tests)."""
    from app.models import (
        ConversationMessage,
        ConversationSession,
        EmergingIssue,
        EmergingIssueMember,
        Feedback,
        ResolutionAttempt,
        SupportCase,
    )

    for model in (Feedback, ResolutionAttempt, EmergingIssueMember, EmergingIssue, ConversationMessage, ConversationSession):
        db.execute(delete(model))
    db.execute(delete(CandidateCase).where(CandidateCase.origin == "live_feedback"))
    db.execute(delete(SupportCase))
    db.commit()
