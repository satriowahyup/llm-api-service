"""Unit tests for GeminiProvider using a mocked async google-genai client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from llm_api_service.config import ProviderConfig
from llm_api_service.core.exceptions import ProviderAuthError
from llm_api_service.core.retry import RetryConfig
from llm_api_service.providers.base import ChatMessage, LLMRequest
from llm_api_service.providers.gemini import GeminiProvider


class FakeAsyncInteractions:
    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return await self._handler(**kwargs)


class FakeGenAIClient:
    def __init__(self, handler) -> None:
        self.interactions_api = FakeAsyncInteractions(handler)
        self.aio = SimpleNamespace(interactions=self.interactions_api)


def _gemini_config() -> ProviderConfig:
    return ProviderConfig(
        name="gemini",
        api_key="test-gemini-key",
        base_url=None,
        default_model="gemini-4-hydrogen",
        default_max_tokens=1024,
    )


async def test_gemini_generate_builds_stateless_steps_and_parses_usage() -> None:
    async def handler(**_kwargs: Any) -> Any:
        return SimpleNamespace(
            output_text="Asyncio TaskGroup enforces structured concurrency.",
            status="completed",
            usage=SimpleNamespace(
                total_input_tokens=32,
                total_output_tokens=14,
                total_tokens=46,
            ),
        )

    fake_client = FakeGenAIClient(handler)
    provider = GeminiProvider(
        _gemini_config(),
        retry_config=RetryConfig(max_retries=2, base_delay=0.001, max_delay=0.01),
        client=fake_client,
    )

    resp = await provider.generate(
        LLMRequest(
            model="gemini-4-hydrogen",
            system_prompt="Be concise.",
            temperature=0.3,
            max_tokens=256,
            messages=[
                ChatMessage(role="user", content="Hi"),
                ChatMessage(role="assistant", content="Hello!"),
                ChatMessage(role="user", content="Explain TaskGroup"),
            ],
        )
    )

    assert resp.content == "Asyncio TaskGroup enforces structured concurrency."
    assert resp.usage.input_tokens == 32
    assert resp.usage.output_tokens == 14
    assert resp.usage.total_tokens == 46

    sent = fake_client.interactions_api.calls[0]
    assert sent["model"] == "gemini-4-hydrogen"
    assert sent["store"] is False
    assert sent["system_instruction"] == "Be concise."
    assert sent["generation_config"] == {"temperature": 0.3, "max_output_tokens": 256}
    assert len(sent["input"]) == 3
    assert sent["input"][0]["type"] == "user_input"
    assert sent["input"][1]["type"] == "model_output"


async def test_gemini_stream_yields_deltas_and_final_usage() -> None:
    async def event_gen() -> AsyncIterator[Any]:
        yield SimpleNamespace(event_type="interaction.created")
        yield SimpleNamespace(
            event_type="step.delta",
            delta=SimpleNamespace(type="text", text="Hello "),
        )
        yield SimpleNamespace(
            event_type="step.delta",
            delta=SimpleNamespace(type="text", text="Gemini!"),
        )
        yield SimpleNamespace(
            event_type="interaction.completed",
            interaction=SimpleNamespace(
                status="completed",
                usage=SimpleNamespace(
                    total_input_tokens=15,
                    total_output_tokens=8,
                    total_tokens=23,
                ),
            ),
        )

    async def handler(**_kwargs: Any) -> Any:
        return event_gen()

    provider = GeminiProvider(
        _gemini_config(),
        retry_config=RetryConfig(max_retries=1, base_delay=0.001, max_delay=0.01),
        client=FakeGenAIClient(handler),
    )

    chunks = [
        c
        async for c in provider.stream(
            LLMRequest(
                model="gemini-4-hydrogen",
                messages=[ChatMessage(role="user", content="Say hi")],
            )
        )
    ]

    texts = [c.delta_text for c in chunks if c.delta_text]
    assert "".join(texts) == "Hello Gemini!"
    final = chunks[-1]
    assert final.is_final is True
    assert final.usage is not None
    assert final.usage.total_tokens == 23


async def test_gemini_retries_transient_503_and_fails_fast_on_401() -> None:
    class FakeSDKError(Exception):
        def __init__(self, status_code: int, message: str) -> None:
            super().__init__(message)
            self.status_code = status_code

    attempts = 0

    async def flaky_handler(**_kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FakeSDKError(503, "UNAVAILABLE")
        return SimpleNamespace(
            output_text="Recovered",
            status="completed",
            usage=SimpleNamespace(total_input_tokens=5, total_output_tokens=3, total_tokens=8),
        )

    provider = GeminiProvider(
        _gemini_config(),
        retry_config=RetryConfig(max_retries=2, base_delay=0.001, max_delay=0.01),
        client=FakeGenAIClient(flaky_handler),
    )
    resp = await provider.generate(
        LLMRequest(model="gemini-4-hydrogen", messages=[ChatMessage(role="user", content="Ping")])
    )
    assert resp.content == "Recovered"
    assert attempts == 2

    async def auth_fail_handler(**_kwargs: Any) -> Any:
        raise FakeSDKError(401, "API_KEY_INVALID")

    auth_provider = GeminiProvider(
        _gemini_config(),
        retry_config=RetryConfig(max_retries=2, base_delay=0.001, max_delay=0.01),
        client=FakeGenAIClient(auth_fail_handler),
    )
    with pytest.raises(ProviderAuthError):
        await auth_provider.generate(
            LLMRequest(
                model="gemini-4-hydrogen",
                messages=[ChatMessage(role="user", content="Ping")],
            )
        )
