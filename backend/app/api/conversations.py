"""Conversations: the customer chat (user portal) and the agent inbox (admin portal)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies import get_container, get_db
from app.models import ConversationMessage, ConversationSession, SupportCase
from app.schemas.common import SESSION_PATTERN
from app.schemas.conversation import (
    AgentMessage,
    ConversationOut,
    ConversationReply,
    HandoffAction,
    MessageRequest,
    StartConversation,
)
from app.services import handoff
from app.services.adaptive_resolution import case_summary
from app.services.memory import summarize_state
from app.utils.errors import NotFoundError, OutOfScope
from app.utils.text import truncate

router = APIRouter(tags=["conversations"])
SESSION = Path(..., pattern=SESSION_PATTERN)


def _session(db: Session, session_id: str) -> ConversationSession:
    session = db.get(ConversationSession, session_id)
    if session is None:
        raise NotFoundError(f"Conversation {session_id} not found")
    return session


def conversation_payload(db: Session, session: ConversationSession) -> dict:
    messages = db.scalars(select(ConversationMessage).where(ConversationMessage.session_id == session.id)
                          .order_by(ConversationMessage.id)).all()
    cases = db.scalars(select(SupportCase).where(SupportCase.session_id == session.id)
                       .order_by(SupportCase.created_at)).all()
    return {
        "session_id": session.id, "title": session.title, "customer_name": session.customer_name or "Customer",
        "channel": session.channel or "agent_console", "handoff_status": session.handoff_status or "bot",
        "handoff_reason": session.handoff_reason, "assigned_agent": session.assigned_agent,
        "agent_unread": session.agent_unread or 0, "queue_position": handoff.queue_position(db, session),
        "memory": session.memory or {},
        "memory_summary": summarize_state(session.memory or {}),
        "messages": [{"id": m.id, "role": m.role, "message": m.message, "metadata": m.extra or {},
                      "created_at": m.created_at.isoformat()} for m in messages],
        "cases": [case_summary(c) for c in cases],
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def start_conversation(body: StartConversation, db: Session = Depends(get_db)) -> dict:
    """Customer portal: start a new chat."""
    session = ConversationSession(id=f"chat-{uuid.uuid4().hex[:12]}", title="New conversation", memory={},
                                  customer_name=body.customer_name, channel="customer_app", handoff_status="bot")
    db.add(session)
    db.flush()
    handoff.post(db, session, "assistant",
                 f"Hi {body.customer_name}! What can I help you with today? Tell me what's going on with your phone, "
                 f"internet, SIM or bill, and if you'd rather talk to a person, just ask.", {"type": "greeting"})
    db.commit()
    return conversation_payload(db, session)


@router.get("/conversations")
def list_conversations(handoff_status: str | None = Query(None, pattern="^(bot|needs_agent|agent|closed)$"),
                       channel: str | None = Query(None, pattern="^(customer_app|agent_console)$"),
                       limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    """Admin inbox: chats needing an agent first, then most recently active."""
    stmt = select(ConversationSession)
    if handoff_status:
        stmt = stmt.where(ConversationSession.handoff_status == handoff_status)
    if channel:
        stmt = stmt.where(ConversationSession.channel == channel)
    rows = db.scalars(stmt.order_by(ConversationSession.updated_at.desc()).limit(limit)).all()
    priority = {"needs_agent": 0, "agent": 1, "bot": 2, "closed": 3}
    rows = sorted(rows, key=lambda r: priority.get(r.handoff_status or "bot", 2))
    items = []
    for r in rows:
        last = db.scalars(select(ConversationMessage).where(ConversationMessage.session_id == r.id)
                          .order_by(ConversationMessage.id.desc()).limit(1)).first()
        open_cases = db.scalar(select(func.count()).select_from(SupportCase).where(
            SupportCase.session_id == r.id, SupportCase.status.in_(("awaiting_feedback", "retry_pending",
                                                                     "needs_more_info", "escalated")))) or 0
        items.append({"session_id": r.id, "title": r.title, "customer_name": r.customer_name or "Customer",
                      "channel": r.channel or "agent_console", "handoff_status": r.handoff_status or "bot",
                      "handoff_reason": r.handoff_reason, "assigned_agent": r.assigned_agent,
                      "agent_unread": r.agent_unread or 0, "open_cases": open_cases,
                      "memory_summary": summarize_state(r.memory or {}),
                      "last_message": truncate(last.message.split("\n")[0], 120) if last else "",
                      "last_role": last.role if last else None,
                      "updated_at": r.updated_at.isoformat() if r.updated_at else None})
    counts = dict(db.execute(select(ConversationSession.handoff_status, func.count())
                             .group_by(ConversationSession.handoff_status)).all())
    return {"items": items, "counts": counts}


@router.get("/conversations/{session_id}", response_model=ConversationOut)
def get_conversation(session_id: str = SESSION, db: Session = Depends(get_db)) -> dict:
    return conversation_payload(db, _session(db, session_id))


@router.post("/conversations/{session_id}/message", response_model=ConversationReply)
def post_message(body: MessageRequest, session_id: str = SESSION, db: Session = Depends(get_db)) -> dict:
    """Customer message. The bot answers unless a human agent has taken over the chat."""
    session = db.get(ConversationSession, session_id)
    if session is not None:
        handoff.reopen_if_closed(db, session)
        if session.handoff_status in ("needs_agent", "agent"):
            session.agent_unread = (session.agent_unread or 0) + 1
        if session.handoff_status == "agent":
            get_container().services.memory.add_message(db, session, "user", body.message, {"routed_to": "agent"})
            db.commit()
            return {"session_id": session_id, "handled_by": "agent", "assistant_message": None, "resolution": None,
                    "conversation": conversation_payload(db, session)}
        db.flush()
    try:
        result = get_container().pipeline.resolve(db, session_id=session_id, complaint=body.message,
                                                  guided_category=body.guided_category, input_mode="free_text")
    except OutOfScope as exc:  # greeting or non-telecom question: the reply is already in the chat
        return {"session_id": session_id, "handled_by": "bot", "assistant_message": exc.message, "resolution": None,
                "conversation": conversation_payload(db, _session(db, session_id))}
    session = _session(db, session_id)
    last = db.scalars(select(ConversationMessage).where(ConversationMessage.session_id == session_id,
                                                         ConversationMessage.role == "assistant")
                      .order_by(ConversationMessage.id.desc()).limit(1)).first()
    db.commit()
    return {"session_id": session_id, "handled_by": "bot",
            "assistant_message": last.message if last else result["resolution"]["summary"], "resolution": result,
            "conversation": conversation_payload(db, session)}


@router.post("/conversations/{session_id}/handoff", response_model=ConversationOut)
def change_handoff(body: HandoffAction, session_id: str = SESSION, db: Session = Depends(get_db)) -> dict:
    """request / cancel (customer) | take | release | close (admin)."""
    if body.action == "request":
        session = handoff.request_agent(db, session_id, body.reason or "Customer asked for a human agent", by="customer")
    elif body.action == "cancel":
        session = handoff.cancel_request(db, session_id)
    elif body.action == "take":
        session = handoff.take(db, session_id, body.agent)
    elif body.action == "release":
        session = handoff.release(db, session_id, body.agent)
    else:
        session = handoff.close(db, session_id, body.agent, resolved=body.resolved)
    db.commit()
    return conversation_payload(db, session)


@router.post("/conversations/{session_id}/agent-message", response_model=ConversationOut)
def send_agent_message(body: AgentMessage, session_id: str = SESSION, db: Session = Depends(get_db)) -> dict:
    """Admin: a human agent replies to the customer (takes over the chat if needed)."""
    handoff.agent_message(db, session_id, body.agent, body.message)
    db.commit()
    return conversation_payload(db, _session(db, session_id))


@router.post("/conversations/{session_id}/read", response_model=ConversationOut)
def mark_read(session_id: str = SESSION, db: Session = Depends(get_db)) -> dict:
    session = _session(db, session_id)
    session.agent_unread = 0
    db.commit()
    return conversation_payload(db, session)
