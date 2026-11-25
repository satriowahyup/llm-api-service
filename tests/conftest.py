"""Shared pytest fixtures and helpers for unit and integration tests (SQLite & PostgreSQL)."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from llm_api_service.config import ProviderName, Settings
from llm_api_service.db.database import DatabaseManager
from llm_api_service.db.models import Base
from llm_api_service.main import create_app
from llm_api_service.providers.base import (
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
)
from llm_api_service.providers.registry import ProviderRegistry


def make_mock_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient backed by MockTransport for deterministic provider tests."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def parse_sse_events(raw_text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse raw SSE response text into a list of (event_name, json_payload) tuples."""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw_text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        payload: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                payload = json.loads(line.removeprefix("data:").strip())
        events.append((event_name, payload))
    return events


@dataclass
class FakeLLMProvider:
    """Deterministic mock LLM provider recording all requests for assertions."""

    name: str
    response_text: str = "Hello from mock LLM!"
    stream_deltas: list[str] = field(default_factory=lambda: ["Hello ", "from ", "stream!"])
    usage: LLMUsage = field(
        default_factory=lambda: LLMUsage(input_tokens=20, output_tokens=10, total_tokens=30)
    )
    error_to_raise: Exception | None = None
    mid_stream_error: Exception | None = None
    requests: list[LLMRequest] = field(default_factory=list)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.error_to_raise is not None:
            raise self.error_to_raise
        return LLMResponse(
            content=self.response_text,
            model=request.model,
            provider=self.name,
            usage=self.usage,
            finish_reason="stop",
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        self.requests.append(request)
        if self.error_to_raise is not None:
            raise self.error_to_raise
        for idx, text in enumerate(self.stream_deltas):
            if idx == 1 and self.mid_stream_error is not None:
                raise self.mid_stream_error
            yield LLMStreamChunk(delta_text=text)
        yield LLMStreamChunk(is_final=True, usage=self.usage, finish_reason="stop")

    async def aclose(self) -> None:
        return None


@pytest.fixture
def test_settings() -> Settings:
    db_url = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    return Settings(
        database_url=db_url,
        db_auto_create_tables=True,
        default_provider="gemini",
        gemini_default_model="gemini-4-hydrogen",
        anthropic_default_model="claude-sonnet-4-6",
        openai_default_model="gpt-4o-mini",
        ollama_default_model="llama3.2",
        llm_max_retries=2,
        llm_retry_base_delay=0.01,
        llm_retry_max_delay=0.05,
        log_level="WARNING",
    )


@pytest.fixture
async def api_env(
    test_settings: Settings,
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[ProviderName, FakeLLMProvider], DatabaseManager]]:
    """Yield (AsyncClient, fake_providers, db_manager) backed by SQLite or TEST_DATABASE_URL."""
    db_manager = DatabaseManager(test_settings)
    if db_manager.dialect != "sqlite":
        async with db_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await db_manager.init_tables()

    providers: dict[ProviderName, FakeLLMProvider] = {
        "gemini": FakeLLMProvider(name="gemini", response_text="Gemini reply"),
        "anthropic": FakeLLMProvider(name="anthropic", response_text="Claude reply"),
        "openai": FakeLLMProvider(name="openai", response_text="OpenAI reply"),
        "ollama": FakeLLMProvider(name="ollama", response_text="Ollama reply"),
    }
    registry = ProviderRegistry(test_settings)
    for name, provider in providers.items():
        registry.register(name, provider)

    app = create_app(
        test_settings,
        db_manager=db_manager,
        provider_registry=registry,
    )
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, providers, db_manager
    finally:
        await registry.aclose()
        if db_manager.dialect != "sqlite":
            async with db_manager.engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        await db_manager.dispose()
