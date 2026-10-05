"""Session-based conversation memory.

Stores every message in `conversation_messages` and a compact structured state in
`conversation_sessions.memory` (product, intent, issue, entities, troubleshooting,
previous resolutions, feedback). Follow-ups such as "Mostly at night." inherit the
active issue so "it" resolves to the right product/intent. Prompt context is
bounded by MEMORY_MAX_MESSAGES and MEMORY_MAX_CHARS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ConversationMessage, ConversationSession
from app.models._common import utcnow
from app.services.classifier import Analysis
from app.services.entity_extractor import mask_sensitive
from app.services.taxonomy import TaxonomySnapshot
from app.utils.text import tokenize, truncate

_FOLLOWUP = re.compile(r"\b(it|its|this|that|same|still|again|also|mostly|only|usually|sometimes|yes|no|"
                       r"didn't|did not|doesn't|happens|tried)\b", re.I)


@dataclass
class MemoryContext:
    session_id: str
    state: dict
    turns: list[dict] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return summarize_state(self.state)


def summarize_state(state: dict) -> str:
    if not state:
        return ""
    parts = []
    if state.get("issue"):
        parts.append(f"Active issue: {state['issue']}")
    if state.get("intent") and state.get("intent") != "unknown":
        parts.append(f"intent={state['intent']}")
    if state.get("product"):
        parts.append(f"product={state['product']}")
    if state.get("entities"):
        parts.append("details: " + ", ".join(f"{e['type']}={e['value']}" for e in state["entities"][-8:]))
    if state.get("troubleshooting"):
        parts.append("already tried: " + "; ".join(state["troubleshooting"][-5:]))
    if state.get("previous_resolutions"):
        last = state["previous_resolutions"][-1]
        parts.append(f"last resolution ({last['case_id']} attempt {last['attempt']}): {last['status']}")
    if state.get("feedback"):
        last = state["feedback"][-1]
        parts.append(f"last feedback: {last['outcome']} on attempt {last['attempt']}")
    return " | ".join(parts)


class MemoryService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def get_or_create(self, db: Session, session_id: str) -> ConversationSession:
        session = db.get(ConversationSession, session_id)
        if session is None:
            session = ConversationSession(id=session_id, title="New conversation", memory={})
            db.add(session)
            db.flush()
        return session

    def add_message(self, db: Session, session: ConversationSession, role: str, message: str, metadata: dict | None = None) -> ConversationMessage:
        msg = ConversationMessage(session_id=session.id, role=role, message=mask_sensitive(message), extra=metadata or {})
        db.add(msg)
        session.updated_at = utcnow()
        if role == "user" and session.title == "New conversation":
            session.title = truncate(message, 80)
        db.flush()
        return msg

    def load(self, db: Session, session: ConversationSession) -> MemoryContext:
        rows = db.scalars(select(ConversationMessage).where(ConversationMessage.session_id == session.id)
                          .order_by(ConversationMessage.id.desc()).limit(self.settings.memory_max_messages)).all()
        turns, budget = [], self.settings.memory_max_chars
        for row in rows:  # newest first; stop when the character budget is used
            text = truncate(row.message, 400)
            if budget - len(text) < 0:
                break
            budget -= len(text)
            turns.append({"role": row.role, "message": text, "created_at": row.created_at.isoformat()})
        turns.reverse()
        return MemoryContext(session.id, dict(session.memory or {}), turns)

    def apply(self, context: MemoryContext, text: str, analysis: Analysis, taxonomy: TaxonomySnapshot) -> tuple[str, Analysis]:
        """Resolve follow-ups against the active issue; returns (effective_query, analysis)."""
        state = context.state
        active_intent = state.get("intent")
        effective = text
        if active_intent and active_intent != "unknown" and analysis.intent == "unknown":
            # Only genuine follow-ups inherit the active issue: very short replies
            # ("Mostly at night.") or messages that refer back to it ("it still drops").
            # A new, self-contained complaint must not be hijacked by memory.
            length = len(tokenize(text))
            if length <= 6 or (_FOLLOWUP.search(text) and length <= 15):
                info = taxonomy.intents.get(active_intent)
                analysis.intent = active_intent
                analysis.intent_display = info.display_name if info else active_intent
                analysis.intent_confidence = round(min(0.85, float(state.get("intent_confidence", 0.7)) * 0.9), 3)
                analysis.classification_method = "memory_carryover"
                analysis.product = state.get("product") or analysis.product
                if info:
                    analysis.support_category = info.support_category
                    analysis.domain_category = info.domain_category
                    analysis.category = taxonomy.top_category(info.support_category)
                    analysis.subcategory = taxonomy.subcategory(info.support_category)
                analysis.used_memory = True
                effective = f"{state.get('issue', '')} Follow-up: {text}".strip()
        # Carry known details (time, devices, prior troubleshooting) into this turn.
        if state.get("entities") and (analysis.used_memory or analysis.intent == active_intent):
            current = {(e["type"], e["value"].lower()) for e in analysis.entities}
            analysis.memory_entities = [e for e in state["entities"] if (e["type"], e["value"].lower()) not in current][-10:]
            if analysis.intent == active_intent:
                analysis.used_memory = True
        return effective, analysis

    def troubleshooting(self, context: MemoryContext, analysis: Analysis) -> list[str]:
        tried = list(context.state.get("troubleshooting", [])) if analysis.used_memory else []
        tried += [e["value"] for e in analysis.entities if e["type"] == "troubleshooting"]
        return list(dict.fromkeys(tried))[-10:]

    def update_after_resolution(self, session: ConversationSession, analysis: Analysis, complaint: str, case_id: str,
                                attempt: int, status: str, summary: str) -> None:
        state = dict(session.memory or {})
        switched = analysis.intent != state.get("intent") and not analysis.used_memory
        if switched or not state.get("issue"):
            # New, self-contained complaint: start a fresh issue context (resolution
            # history and feedback are kept for the session).
            state.update({"intent": analysis.intent, "issue": truncate(complaint, 240), "entities": [],
                          "troubleshooting": [], "customer_context": []})
        state["intent_display"] = analysis.intent_display
        state["intent_confidence"] = analysis.intent_confidence
        state["product"] = analysis.product if analysis.product != "unknown" else state.get("product")
        state["category"] = analysis.category
        merged = list(state.get("entities", []))
        seen = {(e["type"], e["value"].lower()) for e in merged}
        for ent in analysis.entities:
            key = (ent["type"], ent["value"].lower())
            if key not in seen:
                merged.append(ent)
                seen.add(key)
        state["entities"] = merged[-15:]
        tried = state.get("troubleshooting", []) + [e["value"] for e in analysis.entities if e["type"] == "troubleshooting"]
        state["troubleshooting"] = list(dict.fromkeys(tried))[-10:]
        context = [e["value"] for e in analysis.entities if e["type"] == "customer_context"]
        state["customer_context"] = list(dict.fromkeys(state.get("customer_context", []) + context))[-5:]
        history = state.get("previous_resolutions", [])
        history.append({"case_id": case_id, "attempt": attempt, "status": status, "summary": truncate(summary, 200)})
        state["previous_resolutions"] = history[-5:]
        state["last_case_id"] = case_id
        session.memory = state
        session.updated_at = utcnow()

    def record_feedback(self, session: ConversationSession, case_id: str, attempt: int, outcome: str, comment: str | None) -> None:
        state = dict(session.memory or {})
        fb = state.get("feedback", [])
        fb.append({"case_id": case_id, "attempt": attempt, "outcome": outcome, "comment": truncate(comment or "", 200)})
        state["feedback"] = fb[-5:]
        session.memory = state
        session.updated_at = utcnow()
