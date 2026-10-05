"""Intent / class management: list intents and create new ones (manually or from an
emerging issue). Creating an intent saves the taxonomy, its examples, a KB article,
embeddings and the vector index, and makes it available to classification."""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CandidateCase,
    EmergingIssue,
    IntentTaxonomy,
    KnowledgeArticle,
    SupportCase,
    Ticket,
)
from app.models._common import utcnow
from app.services.knowledge_evolution import KnowledgeService, article_to_dict
from app.services.taxonomy import taxonomy_service
from app.utils.errors import ConflictError, NotFoundError, ValidationFailed
from app.utils.text import tokenize

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,60}$")


def intent_to_dict(row: IntentTaxonomy, counts: dict | None = None) -> dict:
    data = {
        "name": row.name, "display_name": row.display_name, "description": row.description,
        "domain_category": row.domain_category, "support_category": row.support_category,
        "default_product": row.default_product, "keywords": row.keywords, "example_complaints": row.example_complaints,
        "clarifying_question": row.clarifying_question, "status": row.status, "origin": row.origin,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if counts is not None:
        data.update(counts)
    return data


class IntentAdminService:
    def __init__(self, knowledge: KnowledgeService):
        self.knowledge = knowledge

    def list_intents(self, db: Session) -> dict:
        tickets = dict(db.execute(select(Ticket.intent, func.count()).group_by(Ticket.intent)).all())
        cases = dict(db.execute(select(SupportCase.intent, func.count()).group_by(SupportCase.intent)).all())
        articles = dict(db.execute(select(KnowledgeArticle.intent, func.count()).where(
            KnowledgeArticle.is_latest.is_(True), KnowledgeArticle.status == "ACTIVE").group_by(KnowledgeArticle.intent)).all())
        rows = db.scalars(select(IntentTaxonomy).order_by(IntentTaxonomy.support_category, IntentTaxonomy.name)).all()
        taxonomy = taxonomy_service.get(db)
        categories = [{"name": n, "parent_name": c["parent_name"], "icon": c["icon"], "description": c["description"]}
                      for n, c in taxonomy.categories.items()]
        return {
            "intents": [intent_to_dict(r, {"ticket_count": tickets.get(r.name, 0), "case_count": cases.get(r.name, 0),
                                           "active_articles": articles.get(r.name, 0)}) for r in rows],
            "categories": categories,
            "domain_categories": sorted(taxonomy.domain_categories),
        }

    def create_intent(self, db: Session, *, name: str, display_name: str | None, description: str, parent_category: str,
                      example_complaints: list[str], keywords: list[str] | None, resolution_title: str | None,
                      resolution_steps: list[str] | None, domain_category: str | None = None,
                      clarifying_question: str | None = None, origin: str = "admin", created_by: str = "admin",
                      emerging_issue_id: str | None = None) -> dict:
        name = name.strip().lower()
        if not NAME_RE.match(name):
            raise ValidationFailed("Intent name must be snake_case: lowercase letters, digits and underscores (3-61 chars)")
        taxonomy = taxonomy_service.get(db)
        if parent_category not in taxonomy.categories:
            raise ValidationFailed(f"Unknown parent category '{parent_category}'")
        examples = [e.strip() for e in example_complaints if e and e.strip()]
        if not examples:
            raise ValidationFailed("At least one example complaint is required")
        existing = db.scalar(select(IntentTaxonomy).where(IntentTaxonomy.name == name))
        issue = None
        if emerging_issue_id:
            issue = db.get(EmergingIssue, emerging_issue_id)
            if issue is None:
                raise NotFoundError(f"Emerging issue {emerging_issue_id} not found")
            if issue.status in ("APPROVED", "REJECTED"):
                raise ConflictError(f"Emerging issue is already {issue.status}")
        if existing and not issue:
            raise ConflictError(f"Intent '{name}' already exists")

        kw = [k.strip().lower() for k in (keywords or []) if k and k.strip()]
        if not kw:
            # Derive conservative multi-word keywords from the examples' distinctive tokens.
            tokens = [t for e in examples for t in tokenize(e) if len(t) > 3]
            common = [t for t in dict.fromkeys(tokens) if sum(t in tokenize(e) for e in examples) >= max(1, len(examples) // 2)]
            kw = common[:3]
        if existing:  # emerging issue mapped onto an existing intent: enrich instead of duplicating
            existing.example_complaints = list(dict.fromkeys((existing.example_complaints or []) + examples))[:20]
            existing.keywords = list(dict.fromkeys((existing.keywords or []) + kw))
            existing.updated_at = utcnow()
            intent_row = existing
        else:
            intent_row = IntentTaxonomy(
                name=name, display_name=(display_name or name.replace("_", " ").title()).strip(),
                description=description.strip(), domain_category=(domain_category or "EMERGING").upper(),
                support_category=parent_category, default_product=None, keywords=kw, example_complaints=examples,
                clarifying_question=clarifying_question, status="active", origin=origin,
            )
            db.add(intent_row)
        db.flush()
        taxonomy_service.invalidate()

        article = None
        if resolution_steps:
            steps = [s.strip() for s in resolution_steps if s and s.strip()]
            if steps:
                content = "\n".join([f"Symptoms: {description.strip() or examples[0]}", "Resolution steps:",
                                     *[f"{i}. {s}" for i, s in enumerate(steps, 1)],
                                     "Escalate when: The steps above do not resolve the issue.",
                                     f"Caution: Created by {created_by} through intent management; verify before extending.",
                                     f"Source note: {'emerging issue ' + emerging_issue_id if emerging_issue_id else 'admin authored'}."])
                article = self.knowledge.create_article(
                    db, title=resolution_title or f"{intent_row.display_name}: resolution", content=content,
                    category=parent_category, intent=name, status="ACTIVE",
                    source="emerging_issue_review" if emerging_issue_id else "admin_authored", created_by=created_by)

        if issue is not None:
            issue.status = "APPROVED"
            issue.created_intent = name
            issue.created_article_id = article.article_id if article else None
            issue.updated_at = utcnow()
            # Relabel the clustered cases / candidates with the new intent.
            from app.models import EmergingIssueMember

            for member in db.scalars(select(EmergingIssueMember).where(EmergingIssueMember.emerging_issue_id == issue.id)):
                target = db.get(SupportCase if member.member_type == "case" else CandidateCase, member.member_id)
                if target is not None and target.intent == "unknown":
                    target.intent = name
        db.flush()
        return {"intent": intent_to_dict(intent_row), "article": article_to_dict(article) if article else None,
                "emerging_issue_id": emerging_issue_id, "classification_ready": True}
