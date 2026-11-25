"""Unit tests for async exponential backoff retry utility."""

from __future__ import annotations

import pytest

from llm_api_service.core.exceptions import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from llm_api_service.core.retry import (
    RetryConfig,
    calculate_backoff_delay,
    parse_retry_after,
    retry_async,
)


async def test_retry_succeeds_after_transient_failures() -> None:
    attempts = 0
    recorded_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded_delays.append(delay)

    async def flaky_op() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ProviderUnavailableError("temporary overload")
        return "ok"

    result = await retry_async(
        flaky_op,
        config=RetryConfig(max_retries=3, base_delay=0.5, max_delay=4.0, jitter_ratio=0.0),
        sleep_fn=fake_sleep,
        jitter_fn=lambda _a, _b: 0.0,
    )

    assert result == "ok"
    assert attempts == 3
    assert recorded_delays == [0.5, 1.0]


async def test_non_retryable_error_fails_fast() -> None:
    attempts = 0
    slept = False

    async def fake_sleep(_delay: float) -> None:
        nonlocal slept
        slept = True

    async def auth_fail() -> str:
        nonlocal attempts
        attempts += 1
        raise ProviderAuthError("invalid key")

    with pytest.raises(ProviderAuthError):
        await retry_async(
            auth_fail,
            config=RetryConfig(max_retries=3, base_delay=0.5, max_delay=4.0),
            sleep_fn=fake_sleep,
        )

    assert attempts == 1
    assert slept is False


async def test_retry_respects_retry_after_and_caps_at_max_delay() -> None:
    recorded_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded_delays.append(delay)

    async def rate_limited() -> str:
        raise ProviderRateLimitError("slow down", retry_after=12.0)

    with pytest.raises(ProviderRateLimitError):
        await retry_async(
            rate_limited,
            config=RetryConfig(max_retries=2, base_delay=0.5, max_delay=5.0),
            sleep_fn=fake_sleep,
        )

    assert recorded_delays == [5.0, 5.0]


def test_parse_retry_after_and_backoff_math() -> None:
    assert parse_retry_after("2.5") == 2.5
    assert parse_retry_after(None) is None
    assert parse_retry_after("not-a-date") is None

    cfg = RetryConfig(base_delay=1.0, max_delay=10.0, jitter_ratio=0.25)
    assert calculate_backoff_delay(0, cfg, jitter_fn=lambda _a, b: b) == pytest.approx(1.25)
    assert calculate_backoff_delay(2, cfg, jitter_fn=lambda _a, _b: 0.0) == pytest.approx(4.0)
