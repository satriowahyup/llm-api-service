"""Provider-agnostic LLM domain types and adapter protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Normalized conversation turn."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """Normalized generation request passed to any LLM provider adapter."""

    model: str
    messages: list[ChatMessage]
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Normalized token usage counters."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized non-streaming LLM completion response."""

    content: str
    model: str
    provider: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class LLMStreamChunk:
    """Single incremental delta or final usage chunk emitted during streaming."""

    delta_text: str = ""
    is_final: bool = False
    usage: LLMUsage | None = None
    finish_reason: str | None = None


class BaseLLMProvider(Protocol):
    """Adapter contract implemented by all LLM providers."""

    name: str

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a complete response asynchronously."""
        ...

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Yield incremental response chunks and a final usage chunk."""
        ...

    async def aclose(self) -> None:
        """Release underlying HTTP or SDK resources."""
        ...
