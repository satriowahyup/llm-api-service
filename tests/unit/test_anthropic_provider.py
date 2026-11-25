"""Unit tests for AnthropicProvider using httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from llm_api_service.config import ProviderConfig
from llm_api_service.core.exceptions import ProviderAuthError, ProviderUnavailableError
from llm_api_service.core.retry import RetryConfig
from llm_api_service.providers.anthropic import AnthropicProvider
from llm_api_service.providers.base import ChatMessage, LLMRequest
from tests.conftest import make_mock_client


def _anthropic_config() -> ProviderConfig:
    return ProviderConfig(
        name="anthropic",
        api_key="sk-ant-test",
        base_url="https://api.anthropic.com",
        default_model="claude-sonnet-4-6",
        default_max_tokens=1024,
        api_version="2023-06-01",
    )


async def test_anthropic_generate_headers_payload_and_usage() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "id": "msg_123",
                "model": "claude-sonnet-4-6",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Hello from Claude!"}],
                "usage": {"input_tokens": 25, "output_tokens": 12},
            },
        )

    client = make_mock_client(handler)
    provider = AnthropicProvider(
        _anthropic_config(),
        retry_config=RetryConfig(max_retries=2, base_delay=0.001, max_delay=0.01),
        http_client=client,
    )

    resp = await provider.generate(
        LLMRequest(
            model="claude-sonnet-4-6",
            system_prompt="You are a concise FDE.",
            messages=[ChatMessage(role="user", content="Hi Claude")],
        )
    )
    await client.aclose()

    assert resp.content == "Hello from Claude!"
    assert resp.usage.input_tokens == 25
    assert resp.usage.output_tokens == 12
    assert resp.usage.total_tokens == 37
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["system"] == "You are a concise FDE."
    assert captured["body"]["max_tokens"] == 1024


async def test_anthropic_stream_parses_sse_events_and_usage() -> None:
    msg_start = json.dumps(
        {"type": "message_start", "message": {"usage": {"input_tokens": 18, "output_tokens": 1}}}
    )
    msg_delta = json.dumps(
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 9},
        }
    )
    sse_payload = (
        f"event: message_start\ndata: {msg_start}\n\n"
        'event: ping\ndata: {"type":"ping"}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Claude "}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"streams!"}}\n\n'
        f"event: message_delta\ndata: {msg_delta}\n\n"
        'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_payload.encode(),
        )

    client = make_mock_client(handler)
    provider = AnthropicProvider(
        _anthropic_config(),
        retry_config=RetryConfig(max_retries=1, base_delay=0.001, max_delay=0.01),
        http_client=client,
    )

    chunks = [
        c
        async for c in provider.stream(
            LLMRequest(
                model="claude-sonnet-4-6",
                messages=[ChatMessage(role="user", content="Stream test")],
            )
        )
    ]
    await client.aclose()

    assert "".join(c.delta_text for c in chunks) == "Claude streams!"
    final = chunks[-1]
    assert final.is_final is True
    assert final.usage is not None
    assert final.usage.input_tokens == 18
    assert final.usage.output_tokens == 9
    assert final.usage.total_tokens == 27


async def test_anthropic_retries_http_529_overloaded_and_fails_fast_401() -> None:
    calls = 0

    def overloaded_then_ok(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                529,
                json={"error": {"type": "overloaded_error", "message": "Overloaded"}},
            )
        return httpx.Response(
            200,
            json={
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "Recovered after 529"}],
                "usage": {"input_tokens": 5, "output_tokens": 4},
            },
        )

    client = make_mock_client(overloaded_then_ok)
    provider = AnthropicProvider(
        _anthropic_config(),
        retry_config=RetryConfig(max_retries=2, base_delay=0.001, max_delay=0.01),
        http_client=client,
    )
    resp = await provider.generate(
        LLMRequest(model="claude-sonnet-4-6", messages=[ChatMessage(role="user", content="Hi")])
    )
    await client.aclose()
    assert resp.content == "Recovered after 529"
    assert calls == 2

    def unauthorized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    client2 = make_mock_client(unauthorized)
    provider2 = AnthropicProvider(
        _anthropic_config(),
        retry_config=RetryConfig(max_retries=2, base_delay=0.001, max_delay=0.01),
        http_client=client2,
    )
    with pytest.raises(ProviderAuthError):
        await provider2.generate(
            LLMRequest(model="claude-sonnet-4-6", messages=[ChatMessage(role="user", content="Hi")])
        )
    await client2.aclose()


async def test_anthropic_stream_handles_midstream_overloaded_error() -> None:
    sse_err = (
        "event: error\n"
        'data: {"type":"error","error":{"type":"overloaded_error","message":"Capacity full"}}\n\n'
    )

    client = make_mock_client(lambda _req: httpx.Response(200, content=sse_err.encode()))
    provider = AnthropicProvider(
        _anthropic_config(),
        retry_config=RetryConfig(max_retries=0, base_delay=0.001, max_delay=0.01),
        http_client=client,
    )

    with pytest.raises(ProviderUnavailableError):
        async for _chunk in provider.stream(
            LLMRequest(model="claude-sonnet-4-6", messages=[ChatMessage(role="user", content="Hi")])
        ):
            pass
    await client.aclose()
