"""Integration tests for POST /v1/chat/stream SSE endpoint."""

from __future__ import annotations

from llm_api_service.core.exceptions import ProviderUnavailableError
from tests.conftest import parse_sse_events


async def test_chat_stream_emits_ordered_sse_events_and_persists_metrics(api_env) -> None:
    client, _providers, _db = api_env

    response = await client.post(
        "/v1/chat/stream",
        json={"message": "Stream a greeting", "provider": "anthropic"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache"

    events = parse_sse_events(response.text)
    event_names = [name for name, _ in events]
    assert event_names[0] == "meta"
    assert event_names[-1] == "done"
    assert all(name == "delta" for name in event_names[1:-1])

    meta = events[0][1]
    assert meta["provider"] == "anthropic"
    assert meta["model"] == "claude-sonnet-4-6"

    assembled = "".join(payload["text"] for name, payload in events if name == "delta")
    assert assembled == "Hello from stream!"

    done = events[-1][1]
    assert done["usage"]["total_tokens"] == 30
    assert done["usage"]["estimated_cost_usd"] > 0
    assert done["metrics"]["ttft_ms"] is not None
    assert done["metrics"]["latency_ms"] >= 0

    # Verify DB persistence of streamed message and telemetry
    session_resp = await client.get(f"/v1/sessions/{meta['session_id']}")
    assert session_resp.status_code == 200
    detail = session_resp.json()
    assert detail["message_count"] == 2
    assistant_msg = detail["messages"][1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == "Hello from stream!"
    assert assistant_msg["ttft_ms"] is not None
    assert assistant_msg["estimated_cost_usd"] > 0


async def test_chat_stream_midstream_error_emits_error_event(api_env) -> None:
    client, providers, _db = api_env
    providers["gemini"].mid_stream_error = ProviderUnavailableError("Upstream dropped")

    response = await client.post("/v1/chat/stream", json={"message": "Trigger mid-stream error"})
    assert response.status_code == 200

    events = parse_sse_events(response.text)
    assert events[0][0] == "meta"
    assert events[1][0] == "delta"
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "provider_unavailable"


async def test_chat_stream_unknown_session_returns_404_before_sse(api_env) -> None:
    client, _providers, _db = api_env
    response = await client.post(
        "/v1/chat/stream",
        json={"session_id": "does-not-exist", "message": "Hi"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"
