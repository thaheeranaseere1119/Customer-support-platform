"""Customer <-> admin connectivity: bot-to-human handoff and cross-portal notifications.

Handoff states of a conversation:
    bot          the AI assistant answers
    needs_agent  escalated (customer request, max attempts reached, critical issue); waiting in the admin inbox
    agent        a human agent took over; the bot stays silent and agent replies reach the customer
    closed       the agent closed the chat; a new customer message reopens it with the bot
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConversationMessage, ConversationSession, SupportCase
from app.models._common import utcnow
from app.utils.errors import ConflictError, NotFoundError
from app.utils.logging import log_event

HANDOFF_STATES = ("bot", "needs_agent", "agent", "closed")


def _get(db: Session, session_id: str) -> ConversationSession:
    session = db.get(ConversationSession, session_id)
    if session is None:
        raise NotFoundError(f"Conversation {session_id} not found")
    return session


def post(db: Session, session: ConversationSession, role: str, text: str, metadata: dict | None = None) -> ConversationMessage:
    msg = ConversationMessage(session_id=session.id, role=role, message=text, extra=metadata or {})
    db.add(msg)
    session.updated_at = utcnow()
    db.flush()
    return msg


def notify(db: Session, session_id: str | None, text: str, metadata: dict | None = None) -> None:
    """Post a system notice into a customer's chat (no-op if the session no longer exists)."""
    if not session_id:
        return
    session = db.get(ConversationSession, session_id)
    if session is not None:
        post(db, session, "system", text, {"type": "notice", **(metadata or {})})


def request_agent(db: Session, session_id: str, reason: str, *, by: str = "customer", case_id: str | None = None) -> ConversationSession:
    session = _get(db, session_id)
    if session.handoff_status in ("needs_agent", "agent"):
        return session
    session.handoff_status = "needs_agent"
    session.handoff_reason = reason
    session.agent_unread = (session.agent_unread or 0) + 1
    post(db, session, "system", "Thanks, we're finding someone to help you. You can keep chatting here while you wait.",
         {"type": "handoff", "handoff": "needs_agent", "reason": reason, "requested_by": by, "case_id": case_id})
    log_event("handoff_requested", db=db, session_id=session.id, case_id=case_id, reason=reason, requested_by=by)
    return session


def cancel_request(db: Session, session_id: str) -> ConversationSession:
    """Customer withdraws a pending request for a human agent (only while still waiting)."""
    session = _get(db, session_id)
    if session.handoff_status != "needs_agent":
        raise ConflictError("There is no pending request for a human agent to cancel", code="NO_PENDING_REQUEST")
    session.handoff_status = "bot"
    session.handoff_reason = None
    post(db, session, "system", "Okay, Support IQ will keep helping you here.",
         {"type": "handoff", "handoff": "bot", "cancelled_by": "customer"})
    log_event("handoff_cancelled", db=db, session_id=session.id)
    return session


def queue_position(db: Session, session: ConversationSession) -> int | None:
    """1-based position among chats waiting for an agent, ordered by when they asked."""
    if session.handoff_status != "needs_agent":
        return None
    waiting = select(ConversationSession.id).where(ConversationSession.handoff_status == "needs_agent")
    rows = db.execute(select(ConversationMessage.session_id, ConversationMessage.id, ConversationMessage.extra).where(
        ConversationMessage.session_id.in_(waiting), ConversationMessage.role == "system")).all()
    requested_at: dict[str, int] = {}
    for sid, message_id, extra in rows:  # latest "needs_agent" handoff message per waiting chat
        if (extra or {}).get("handoff") == "needs_agent":
            requested_at[sid] = max(requested_at.get(sid, 0), message_id)
    mine = requested_at.get(session.id, 0)
    return 1 + sum(1 for sid, at in requested_at.items() if sid != session.id and at < mine)


def take(db: Session, session_id: str, agent: str) -> ConversationSession:
    session = _get(db, session_id)
    if session.handoff_status == "agent" and session.assigned_agent == agent:
        return session
    session.handoff_status = "agent"
    session.assigned_agent = agent
    session.agent_unread = 0
    post(db, session, "system", f"{agent} (human agent) joined the chat.", {"type": "handoff", "handoff": "agent", "agent": agent})
    log_event("handoff_taken", db=db, session_id=session.id, agent=agent)
    return session


def release(db: Session, session_id: str, agent: str) -> ConversationSession:
    session = _get(db, session_id)
    if session.handoff_status != "agent":
        raise ConflictError("Only a chat handled by an agent can be handed back to the bot", code="NOT_WITH_AGENT")
    session.handoff_status = "bot"
    session.handoff_reason = None
    session.assigned_agent = None  # the bot owns the chat again; the inbox must not list it as assigned or unread
    session.agent_unread = 0
    post(db, session, "system", f"{agent} handed the chat back to Support IQ. The assistant will answer new messages.",
         {"type": "handoff", "handoff": "bot", "agent": agent})
    log_event("handoff_released", db=db, session_id=session.id, agent=agent)
    return session


def close(db: Session, session_id: str, agent: str, *, resolved: bool) -> ConversationSession:
    session = _get(db, session_id)
    if session.handoff_status == "closed":
        raise ConflictError("Chat is already closed", code="ALREADY_CLOSED")
    session.handoff_status = "closed"
    session.agent_unread = 0
    if resolved:
        for case in db.scalars(select(SupportCase).where(SupportCase.session_id == session.id,
                                                         SupportCase.status.in_(("escalated", "awaiting_feedback",
                                                                                 "retry_pending", "needs_more_info")))):
            case.status = "resolved_by_agent"
            case.updated_at = utcnow()
            # The assistant could not confirm a fix; the agent's answer is new knowledge for human review.
            from app.services.knowledge_evolution import candidate_from_agent_fix
            candidate_from_agent_fix(db, case, agent)
    text = (f"{agent} marked your issue as resolved and closed the chat. Send a new message any time to start again."
            if resolved else f"{agent} closed the chat. Send a new message any time to start again.")
    post(db, session, "system", text, {"type": "handoff", "handoff": "closed", "agent": agent, "resolved": resolved})
    log_event("handoff_closed", db=db, session_id=session.id, agent=agent, resolved=resolved)
    return session


def agent_message(db: Session, session_id: str, agent: str, text: str) -> ConversationMessage:
    session = _get(db, session_id)
    if session.handoff_status != "agent" or session.assigned_agent != agent:
        take(db, session_id, agent)
    return post(db, session, "agent", text, {"agent": agent})


def reopen_if_closed(db: Session, session: ConversationSession) -> None:
    if session.handoff_status == "closed":
        session.handoff_status = "bot"
        session.handoff_reason = None
        session.assigned_agent = None
