"""Pydantic v2 request and response schemas for chat endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm_api_service.config import ProviderName


class ChatRequest(BaseModel):
    """Input payload for POST /v1/chat and POST /v1/chat/stream."""

    session_id: str | None = Field(
        default=None,
        description="Existing session UUID to continue a multi-turn conversation.",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="User prompt text.",
    )
    system_prompt: str | None = Field(
        default=None,
        max_length=20_000,
        description="Optional system instruction (persisted on new sessions or overrides turn).",
    )
    provider: ProviderName | None = Field(
        default=None,
        description="Optional provider override (defaults to session provider or global default).",
    )
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Optional model override.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature.",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        le=65_536,
        description="Maximum output tokens to generate.",
    )


class UsageStats(BaseModel):
    """Token counts and estimated USD cost for a single generation."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class LatencyMetrics(BaseModel):
    """Latency and throughput telemetry for a single generation."""

    ttft_ms: float | None = None
    latency_ms: float
    tokens_per_sec: float | None = None


class ChatResponse(BaseModel):
    """Response payload for POST /v1/chat."""

    session_id: str
    message_id: str
    provider: str
    model: str
    content: str
    usage: UsageStats
    metrics: LatencyMetrics


class HealthResponse(BaseModel):
    """Response payload for GET /health."""

    status: str
    version: str
    database: str
    database_dialect: str
    default_provider: str
    default_model: str
