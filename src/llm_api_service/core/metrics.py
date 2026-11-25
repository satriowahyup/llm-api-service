"""Latency, TTFT, and token throughput measurement utilities."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GenerationMetrics:
    """Computed generation performance metrics."""

    ttft_ms: float | None
    latency_ms: float
    tokens_per_sec: float | None


class GenerationMetricsTracker:
    """Tracks wall-clock generation latency, TTFT (streaming), and output tokens/sec."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._start_ts: float = self._clock()
        self._first_token_ts: float | None = None

    def mark_first_token(self) -> None:
        """Record timestamp of the first non-empty text delta (idempotent)."""
        if self._first_token_ts is None:
            self._first_token_ts = self._clock()

    def finish(self, *, output_tokens: int) -> GenerationMetrics:
        """Finalize metrics at end of generation."""
        end_ts = self._clock()
        latency_s = max(end_ts - self._start_ts, 0.0)
        latency_ms = round(latency_s * 1000.0, 2)

        ttft_ms: float | None = None
        throughput_window_s = latency_s

        if self._first_token_ts is not None:
            ttft_s = max(self._first_token_ts - self._start_ts, 0.0)
            ttft_ms = round(ttft_s * 1000.0, 2)
            decode_s = max(latency_s - ttft_s, 0.0)
            throughput_window_s = decode_s if decode_s > 0 else latency_s

        tokens_per_sec: float | None = None
        if output_tokens > 0 and throughput_window_s > 0:
            tokens_per_sec = round(output_tokens / throughput_window_s, 2)

        return GenerationMetrics(
            ttft_ms=ttft_ms,
            latency_ms=latency_ms,
            tokens_per_sec=tokens_per_sec,
        )
