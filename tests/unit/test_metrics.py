"""Unit tests for latency, TTFT, and tokens/sec measurement."""

from __future__ import annotations

from llm_api_service.core.metrics import GenerationMetricsTracker


class FakeClock:
    def __init__(self, times: list[float]) -> None:
        self._iter = iter(times)

    def __call__(self) -> float:
        return next(self._iter)


def test_non_streaming_metrics_without_ttft() -> None:
    clock = FakeClock([10.0, 12.0])
    tracker = GenerationMetricsTracker(clock=clock)
    metrics = tracker.finish(output_tokens=100)

    assert metrics.ttft_ms is None
    assert metrics.latency_ms == 2000.0
    assert metrics.tokens_per_sec == 50.0


def test_streaming_metrics_with_ttft_and_decode_throughput() -> None:
    # start=1.0, first_token=1.5 (500ms TTFT), end=3.5 (2500ms total, 2000ms decode)
    clock = FakeClock([1.0, 1.5, 3.5])
    tracker = GenerationMetricsTracker(clock=clock)
    tracker.mark_first_token()
    # Second call should be idempotent and not consume another clock tick
    tracker.mark_first_token()
    metrics = tracker.finish(output_tokens=200)

    assert metrics.ttft_ms == 500.0
    assert metrics.latency_ms == 2500.0
    assert metrics.tokens_per_sec == 100.0


def test_zero_output_tokens_handles_division_safely() -> None:
    clock = FakeClock([5.0, 5.5])
    tracker = GenerationMetricsTracker(clock=clock)
    metrics = tracker.finish(output_tokens=0)

    assert metrics.latency_ms == 500.0
    assert metrics.tokens_per_sec is None
