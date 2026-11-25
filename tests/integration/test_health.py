"""Integration tests for GET /health."""

from __future__ import annotations

from unittest.mock import AsyncMock


async def test_health_ok(api_env) -> None:
    client, _providers, db_manager = api_env
    response = await client.get("/health")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert "X-Latency-Ms" in response.headers

    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert data["database_dialect"] == db_manager.dialect
    assert data["default_provider"] == "gemini"
    assert data["default_model"] == "gemini-4-hydrogen"


async def test_health_degraded_when_db_unreachable(api_env, monkeypatch) -> None:
    client, _providers, db_manager = api_env
    monkeypatch.setattr(db_manager, "health_check", AsyncMock(return_value=False))

    response = await client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["database"] == "disconnected"
