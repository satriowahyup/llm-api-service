"""Pydantic v2 schemas for session listing, detail inspection, and message history."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MessageItem(BaseModel):
    """Serialized chat message stored in a session."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    provider: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    ttft_ms: float | None = None
    latency_ms: float | None = None
    tokens_per_sec: float | None = None
    created_at: datetime


class SessionSummary(BaseModel):
    """Aggregated session summary for GET /v1/sessions."""

    id: str
    title: str | None = None
    provider: str
    model: str
    system_prompt: str | None = None
    message_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """Paginated list of sessions."""

    items: list[SessionSummary]
    total: int
    limit: int
    offset: int


class SessionDetailResponse(SessionSummary):
    """Detailed session view including full chronological message history."""

    messages: list[MessageItem]
