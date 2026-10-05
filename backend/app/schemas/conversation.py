from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import StrictModel, clean_user_text
from app.schemas.resolve import ResolveResponse


class MessageRequest(StrictModel):
    message: str = Field(..., min_length=1, max_length=2000)
    guided_category: str | None = Field(None, max_length=64)

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        value = clean_user_text(value)
        if len(value) < 2:
            raise ValueError("Message must contain at least 2 characters")
        return value


class StartConversation(StrictModel):
    customer_name: str = Field("Customer", min_length=1, max_length=80)

    @field_validator("customer_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return clean_user_text(value) or "Customer"


class AgentMessage(StrictModel):
    agent: str = Field("Support agent", min_length=2, max_length=80)
    message: str = Field(..., min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        value = clean_user_text(value)
        if not value:
            raise ValueError("Message cannot be empty")
        return value


class HandoffAction(StrictModel):
    action: Literal["request", "cancel", "take", "release", "close"]
    agent: str = Field("Support agent", min_length=2, max_length=80)
    reason: str | None = Field(None, max_length=300)
    resolved: bool = True


class MessageOut(BaseModel):
    id: int
    role: str
    message: str
    metadata: dict
    created_at: str


class ConversationOut(BaseModel):
    session_id: str
    title: str
    customer_name: str
    channel: str
    handoff_status: Literal["bot", "needs_agent", "agent", "closed"]
    handoff_reason: str | None
    assigned_agent: str | None
    agent_unread: int
    queue_position: int | None = None
    memory: dict
    memory_summary: str
    messages: list[MessageOut]
    cases: list[dict]
    created_at: str | None
    updated_at: str | None


class ConversationReply(BaseModel):
    session_id: str
    handled_by: Literal["bot", "agent"]
    assistant_message: str | None
    resolution: ResolveResponse | None
    conversation: ConversationOut
