"""Async exponential backoff retry engine with jitter and Retry-After support."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from llm_api_service.core.exceptions import AppError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Configuration for exponential backoff retries."""

    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter_ratio: float = 0.25


def parse_retry_after(header_value: str | None) -> float | None:
    """Parse HTTP Retry-After header (seconds or HTTP-date) into delay seconds."""
    if not header_value:
        return None
    stripped = header_value.strip()
    try:
        seconds = float(stripped)
        return max(0.0, seconds)
    except ValueError:
        pass

    try:
        target_dt = parsedate_to_datetime(stripped)
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=UTC)
        delta = (target_dt - datetime.now(UTC)).total_seconds()
        return max(0.0, delta)
    except TypeError, ValueError:
        return None


def calculate_backoff_delay(
    attempt: int,
    config: RetryConfig,
    *,
    retry_after: float | None = None,
    jitter_fn: Callable[[float, float], float] = random.uniform,
) -> float:
    """Compute delay in seconds for the given 0-based retry attempt."""
    if retry_after is not None and retry_after >= 0:
        return min(retry_after, config.max_delay)

    exponential = config.base_delay * (2**attempt)
    jitter = jitter_fn(0.0, exponential * config.jitter_ratio)
    return min(exponential + jitter, config.max_delay)


def default_is_retryable(exc: Exception) -> bool:
    """Check whether an exception should trigger an automatic retry."""
    if isinstance(exc, AppError):
        return exc.retryable
    return False


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    config: RetryConfig,
    is_retryable: Callable[[Exception], bool] = default_is_retryable,
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    jitter_fn: Callable[[float, float], float] = random.uniform,
    operation_name: str = "llm_call",
) -> T:
    """Execute an async operation with exponential backoff and jitter on retryable failures."""
    attempt = 0
    while True:
        try:
            return await operation()
        except Exception as exc:
            if attempt >= config.max_retries or not is_retryable(exc):
                raise

            retry_after = exc.retry_after if isinstance(exc, AppError) else None
            delay = calculate_backoff_delay(
                attempt,
                config,
                retry_after=retry_after,
                jitter_fn=jitter_fn,
            )
            attempt += 1
            logger.warning(
                "Transient provider failure; retrying",
                extra={
                    "operation": operation_name,
                    "retry_attempt": attempt,
                    "max_retries": config.max_retries,
                    "delay_seconds": round(delay, 3),
                    "error_type": type(exc).__name__,
                },
            )
            await sleep_fn(delay)
