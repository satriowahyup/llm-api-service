"""Unit tests for OpenAICompatibleProvider (OpenAI, DeepSeek, Groq, Ollama)."""

from __future__ import annotations

import json

import httpx
import pytest

from llm_api_service.config import ProviderConfig
from llm_api_service.core.exceptions import ProviderAuthError
from llm_api_service.core.retry import RetryConfig
from llm_api_service.providers.base import ChatMessage, LLMRequest
from llm_api_service.providers.openai_compat import OpenAICompatibleProvider
from tests.conftest import make_mock_client


async def test_openai_generate_and_ollama_no_auth_header() -> None:
    captured_headers: dict[str, str] = {}

    def ollama_handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        assert str(request.url) == "http://localhost:11434/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "model": "llama3.2",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Local llama"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    client = make_mock_client(ollama_handler)
    ollama_cfg = ProviderConfig(
        name="ollama",
        api_key=None,
        base_url="http://localhost:11434/v1",
        default_model="llama3.2",
        default_max_tokens=1024,
        requires_api_key=False,
    )
    provider = OpenAICompatibleProvider(
        ollama_cfg,
        retry_config=RetryConfig(max_retries=1, base_delay=0.001, max_delay=0.01),
        http_client=client,
    )

    resp = await provider.generate(
        LLMRequest(
            model="llama3.2",
            system_prompt="Be brief.",
            messages=[ChatMessage(role="user", content="Hello local")],
        )
    )
    await client.aclose()

    assert resp.content == "Local llama"
    assert resp.usage.total_tokens == 18
    assert "authorization" not in captured_headers


async def test_openai_compatible_stream_parses_deltas_and_usage() -> None:
    usage_chunk = json.dumps(
        {
            "choices": [],
            "usage": {"prompt_tokens": 14, "completion_tokens": 6, "total_tokens": 20},
        }
    )
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Fast "},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{"content":"API"},"finish_reason":"stop"}]}\n\n'
        f"data: {usage_chunk}\n\n"
        "data: [DONE]\n\n"
    )
    captured_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content.decode()))
        assert request.headers["authorization"] == "Bearer sk-test"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_body.encode(),
        )

    client = make_mock_client(handler)
    cfg = ProviderConfig(
        name="deepseek",
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        default_max_tokens=1024,
    )
    provider = OpenAICompatibleProvider(
        cfg,
        retry_config=RetryConfig(max_retries=1, base_delay=0.001, max_delay=0.01),
        http_client=client,
    )

    chunks = [
        c
        async for c in provider.stream(
            LLMRequest(
                model="deepseek-chat",
                messages=[ChatMessage(role="user", content="Stream")],
            )
        )
    ]
    await client.aclose()

    assert captured_body["stream"] is True
    assert captured_body["stream_options"] == {"include_usage": True}
    assert "".join(c.delta_text for c in chunks) == "Fast API"
    final = chunks[-1]
    assert final.is_final is True
    assert final.usage is not None
    assert final.usage.total_tokens == 20


async def test_openai_retries_429_and_fails_fast_on_401() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"error": {"message": "Rate limit"}},
            )
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": "OK after 429"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )

    client = make_mock_client(handler)
    cfg = ProviderConfig(
        name="openai",
        api_key="sk-openai",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        default_max_tokens=1024,
    )
    provider = OpenAICompatibleProvider(
        cfg,
        retry_config=RetryConfig(max_retries=2, base_delay=0.001, max_delay=0.01),
        http_client=client,
    )
    resp = await provider.generate(
        LLMRequest(model="gpt-4o-mini", messages=[ChatMessage(role="user", content="Test")])
    )
    await client.aclose()
    assert resp.content == "OK after 429"
    assert attempts == 2

    client2 = make_mock_client(
        lambda _req: httpx.Response(401, json={"error": {"message": "Bad key"}})
    )
    provider2 = OpenAICompatibleProvider(
        cfg,
        retry_config=RetryConfig(max_retries=2, base_delay=0.001, max_delay=0.01),
        http_client=client2,
    )
    with pytest.raises(ProviderAuthError):
        await provider2.generate(
            LLMRequest(model="gpt-4o-mini", messages=[ChatMessage(role="user", content="Test")])
        )
    await client2.aclose()
