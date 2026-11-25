"""Token pricing registry and USD cost estimator for multi-provider LLM models."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TOKENS_PER_MILLION = 1_000_000.0


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """USD price per 1,000,000 input and output tokens."""

    input_per_million: float
    output_per_million: float


# Reference USD pricing per 1M tokens. Local models (Ollama) are always $0.00.
MODEL_PRICING_TABLE: dict[str, ModelPricing] = {
    # Google Gemini
    "gemini-4-hydrogen": ModelPricing(1.50, 7.50),
    "gemini-4-argon": ModelPricing(1.00, 5.00),
    "gemini-4-neon": ModelPricing(2.50, 12.50),
    "gemini-4-carbon": ModelPricing(2.00, 10.00),
    "gemini-3.5-flash-lite": ModelPricing(0.10, 0.40),
    "gemini-3.1-flash-lite": ModelPricing(0.10, 0.40),
    # Anthropic Claude
    "claude-haiku-4-5": ModelPricing(1.00, 5.00),
    "claude-sonnet-4-6": ModelPricing(3.00, 15.00),
    "claude-opus-4-6": ModelPricing(5.00, 25.00),
    "claude-haiku-5-5": ModelPricing(0.10, 0.50),
    "claude-sonnet-5-5": ModelPricing(2.00, 10.00),
    "claude-opus-5-5": ModelPricing(4.00, 20.00),
    # OpenAI
    "gpt-4o": ModelPricing(2.50, 10.00),
    "gpt-4o-mini": ModelPricing(0.15, 0.60),
    "gpt-4.1": ModelPricing(2.00, 8.00),
    "gpt-4.1-mini": ModelPricing(0.40, 1.60),
    "gpt-4.1-nano": ModelPricing(0.10, 0.40),
    "o3-mini": ModelPricing(1.10, 4.40),
    # DeepSeek
    "deepseek-chat": ModelPricing(0.27, 1.10),
    "deepseek-reasoner": ModelPricing(0.55, 2.19),
    # Groq
    "llama-3.3-70b-versatile": ModelPricing(0.59, 0.79),
    "llama-3.1-8b-instant": ModelPricing(0.05, 0.08),
    "mixtral-8x7b-32768": ModelPricing(0.24, 0.24),
}


def resolve_model_pricing(provider: str, model: str) -> ModelPricing | None:
    """Resolve pricing entry by provider and model identifier."""
    if provider.lower() == "ollama":
        return ModelPricing(0.0, 0.0)

    normalized = model.strip().lower()
    if normalized in MODEL_PRICING_TABLE:
        return MODEL_PRICING_TABLE[normalized]

    # Match dated snapshots such as claude-sonnet-4-6-20260101 or gpt-4o-2024-08-06
    for prefix, pricing in sorted(
        MODEL_PRICING_TABLE.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if normalized.startswith(f"{prefix}-"):
            return pricing

    return None


def estimate_cost_usd(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate USD cost rounded to 8 decimal places. Returns 0.0 for local or unknown models."""
    pricing = resolve_model_pricing(provider, model)
    if pricing is None:
        logger.warning(
            "Pricing not configured for model; defaulting cost to 0.0",
            extra={"provider": provider, "model": model},
        )
        return 0.0

    safe_in = max(0, input_tokens)
    safe_out = max(0, output_tokens)
    cost = (safe_in / TOKENS_PER_MILLION) * pricing.input_per_million + (
        safe_out / TOKENS_PER_MILLION
    ) * pricing.output_per_million
    return round(cost, 8)
