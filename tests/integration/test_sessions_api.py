"""Integration tests for GET/DELETE /v1/sessions endpoints."""

from __future__ import annotations

import pytest


async def test_sessions_pagination_aggregation_detail_and_cascade_delete(api_env) -> None:
    client, _providers, _db = api_env

    # Create Session 1 (Gemini + Anthropic cross-provider turns)
    s1_t1 = await client.post("/v1/chat", json={"message": "Session one turn one"})
    s1_id = s1_t1.json()["session_id"]
    cost_t1 = s1_t1.json()["usage"]["estimated_cost_usd"]

    s1_t2 = await client.post(
        "/v1/chat",
        json={"session_id": s1_id, "provider": "anthropic", "message": "Session one turn two"},
    )
    cost_t2 = s1_t2.json()["usage"]["estimated_cost_usd"]

    # Create Session 2 (Ollama local -> $0.00)
    s2 = await client.post(
        "/v1/chat",
        json={"provider": "ollama", "message": "Session two local"},
    )
    s2_id = s2.json()["session_id"]
    assert s2.json()["usage"]["estimated_cost_usd"] == 0.0

    # List sessions with pagination
    list_resp = await client.get("/v1/sessions?limit=1&offset=0")
    assert list_resp.status_code == 200
    page1 = list_resp.json()
    assert page1["total"] == 2
    assert page1["limit"] == 1
    assert len(page1["items"]) == 1
    assert page1["items"][0]["id"] == s2_id  # Most recently updated first

    full_list = (await client.get("/v1/sessions?limit=20&offset=0")).json()
    by_id = {item["id"]: item for item in full_list["items"]}
    assert by_id[s1_id]["message_count"] == 4
    assert by_id[s1_id]["total_tokens"] == 60
    assert by_id[s1_id]["total_cost_usd"] == pytest.approx(round(cost_t1 + cost_t2, 8))
    assert by_id[s2_id]["total_cost_usd"] == 0.0

    # Session detail
    detail_resp = await client.get(f"/v1/sessions/{s1_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert len(detail["messages"]) == 4
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]

    # Delete session (cascade deletes messages)
    del_resp = await client.delete(f"/v1/sessions/{s1_id}")
    assert del_resp.status_code == 204

    # Subsequent GET and DELETE return 404
    assert (await client.get(f"/v1/sessions/{s1_id}")).status_code == 404
    assert (await client.delete(f"/v1/sessions/{s1_id}")).status_code == 404
