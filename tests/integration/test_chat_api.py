"""Integration tests for POST /v1/chat (default Gemini, multi-turn, mid-session switch, errors)."""

from __future__ import annotations

from llm_api_service.core.exceptions import ProviderAuthError, ProviderRateLimitError


async def test_chat_defaults_to_gemini_and_persists_usage(api_env) -> None:
    client, providers, _db = api_env
    response = await client.post("/v1/chat", json={"message": "Explain FastAPI lifespan"})

    assert response.status_code == 200
    assert response.headers["X-Provider"] == "gemini"
    assert response.headers["X-Model"] == "gemini-4-hydrogen"

    data = response.json()
    assert data["provider"] == "gemini"
    assert data["model"] == "gemini-4-hydrogen"
    assert data["content"] == "Gemini reply"
    assert data["usage"]["total_tokens"] == 30
    assert data["usage"]["estimated_cost_usd"] > 0
    assert data["metrics"]["ttft_ms"] is None
    assert data["metrics"]["latency_ms"] >= 0
    assert len(providers["gemini"].requests) == 1


async def test_chat_multi_turn_and_mid_session_provider_switch(api_env) -> None:
    client, providers, _db = api_env

    # Turn 1: Default Gemini
    r1 = await client.post(
        "/v1/chat",
        json={"message": "My name is Satrio.", "system_prompt": "Be helpful."},
    )
    assert r1.status_code == 200
    session_id = r1.json()["session_id"]

    # Turn 2: Switch to Anthropic without model -> must default to claude-sonnet-4-6
    r2 = await client.post(
        "/v1/chat",
        json={"session_id": session_id, "provider": "anthropic", "message": "What is my name?"},
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["session_id"] == session_id
    assert d2["provider"] == "anthropic"
    assert d2["model"] == "claude-sonnet-4-6"
    assert d2["content"] == "Claude reply"

    # Verify Anthropic received full conversation history from Turn 1 + Turn 2
    anthropic_req = providers["anthropic"].requests[0]
    assert anthropic_req.model == "claude-sonnet-4-6"
    assert anthropic_req.system_prompt == "Be helpful."
    assert [(m.role, m.content) for m in anthropic_req.messages] == [
        ("user", "My name is Satrio."),
        ("assistant", "Gemini reply"),
        ("user", "What is my name?"),
    ]

    # Turn 3: Omit provider -> inherit session's latest provider/model (anthropic)
    r3 = await client.post(
        "/v1/chat",
        json={"session_id": session_id, "message": "Thanks!"},
    )
    assert r3.status_code == 200
    assert r3.json()["provider"] == "anthropic"
    assert r3.json()["model"] == "claude-sonnet-4-6"


async def test_chat_error_handling_and_envelope(api_env) -> None:
    client, providers, _db = api_env

    # 404 for unknown session
    not_found = await client.post(
        "/v1/chat",
        json={"session_id": "nonexistent-id", "message": "Hello"},
    )
    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "session_not_found"
    assert not_found.json()["error"]["request_id"] is not None

    # 422 for empty message
    invalid = await client.post("/v1/chat", json={"message": ""})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    # 400 when unconfigured provider (deepseek not registered and no API key in test settings)
    unconfigured = await client.post(
        "/v1/chat",
        json={"provider": "deepseek", "message": "Hello"},
    )
    assert unconfigured.status_code == 400
    assert unconfigured.json()["error"]["code"] == "provider_not_configured"
    # Verify no orphaned session was created
    sessions_resp = await client.get("/v1/sessions")
    assert sessions_resp.json()["total"] == 0

    # 429 rate limit with Retry-After header
    providers["gemini"].error_to_raise = ProviderRateLimitError(
        "Too many requests", retry_after=3.0
    )
    rate_limited = await client.post("/v1/chat", json={"message": "Hello"})
    assert rate_limited.status_code == 429
    assert rate_limited.headers["Retry-After"] == "3"
    assert rate_limited.json()["error"]["code"] == "provider_rate_limit"

    # 401 auth error
    providers["gemini"].error_to_raise = ProviderAuthError("Invalid key")
    auth_err = await client.post("/v1/chat", json={"message": "Hello"})
    assert auth_err.status_code == 401
    assert auth_err.json()["error"]["code"] == "provider_auth_error"
