"""Unit tests for token pricing and USD cost estimation."""

from __future__ import annotations

import pytest

from llm_api_service.core.pricing import estimate_cost_usd, resolve_model_pricing


def test_gemini_4_hydrogen_cost_estimation() -> None:
    cost = estimate_cost_usd(
        provider="gemini",
        model="gemini-4-hydrogen",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert cost == pytest.approx(9.0)


def test_anthropic_dated_snapshot_prefix_matching() -> None:
    pricing = resolve_model_pricing("anthropic", "claude-sonnet-4-6-20260115")
    assert pricing is not None
    cost = estimate_cost_usd(
        provider="anthropic",
        model="claude-sonnet-4-6-20260115",
        input_tokens=500_000,
        output_tokens=100_000,
    )
    assert cost == pytest.approx(3.0)


def test_ollama_local_models_are_always_free() -> None:
    cost = estimate_cost_usd(
        provider="ollama",
        model="llama3.2:latest",
        input_tokens=250_000,
        output_tokens=100_000,
    )
    assert cost == 0.0


def test_unknown_model_falls_back_to_zero() -> None:
    cost = estimate_cost_usd(
        provider="openai",
        model="custom-finetuned-model-xyz",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost == 0.0
