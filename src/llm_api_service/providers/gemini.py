"""Google Gemini LLM provider adapter using google-genai Interactions API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from google import genai

from llm_api_service.config import ProviderConfig
from llm_api_service.core.exceptions import (
    AppError,
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ProviderUpstreamError,
)
from llm_api_service.core.retry import RetryConfig, retry_async
from llm_api_service.providers.base import (
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
)


def _extract_status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    return None


def _map_gemini_error(exc: Exception) -> AppError:
    """Map google-genai SDK / transport exceptions to domain AppError types."""
    if isinstance(exc, AppError):
        return exc

    status = _extract_status_code(exc)
    message = str(exc) or "Gemini provider request failed"
    upper_msg = message.upper()

    if isinstance(exc, TimeoutError) or status == 504 or "DEADLINE_EXCEEDED" in upper_msg:
        return ProviderTimeoutError(f"Gemini request timed out: {message}")
    if status in (401, 403) or "PERMISSION_DENIED" in upper_msg or "API_KEY_INVALID" in upper_msg:
        return ProviderAuthError(f"Gemini authentication failed: {message}")
    if status == 429 or "RESOURCE_EXHAUSTED" in upper_msg:
        return ProviderRateLimitError(f"Gemini rate limit exceeded: {message}")
    if status in (500, 502, 503) or "UNAVAILABLE" in upper_msg or "INTERNAL" in upper_msg:
        return ProviderUnavailableError(f"Gemini service temporarily unavailable: {message}")
    if status in (400, 404, 422) or "INVALID_ARGUMENT" in upper_msg:
        return ProviderBadRequestError(f"Gemini rejected request: {message}")
    return ProviderUpstreamError(f"Gemini upstream error: {message}")


def _extract_gemini_usage(usage_obj: Any) -> LLMUsage:
    if usage_obj is None:
        return LLMUsage()
    input_tokens = int(getattr(usage_obj, "total_input_tokens", None) or 0)
    output_tokens = int(getattr(usage_obj, "total_output_tokens", None) or 0)
    total_tokens = int(getattr(usage_obj, "total_tokens", None) or (input_tokens + output_tokens))
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _extract_gemini_text(interaction: Any) -> str:
    output_text = getattr(interaction, "output_text", None)
    if isinstance(output_text, str):
        return output_text

    steps = getattr(interaction, "steps", None) or []
    parts: list[str] = []
    for step in steps:
        if getattr(step, "type", None) == "model_output":
            for item in getattr(step, "content", None) or []:
                if getattr(item, "type", None) == "text":
                    text = getattr(item, "text", None)
                    if text:
                        parts.append(text)
    return "".join(parts)


class GeminiProvider:
    """Adapter for Google Gemini via google-genai async Interactions API (v1)."""

    name: str = "gemini"

    def __init__(
        self,
        config: ProviderConfig,
        *,
        retry_config: RetryConfig,
        timeout_seconds: float = 60.0,
        client: Any | None = None,
    ) -> None:
        self._config = config
        self._retry_config = retry_config
        self._timeout_seconds = timeout_seconds
        # Disable SDK-internal retries so retry_async is the single retry orchestrator
        # (prevents nested retry amplification on 429/503 responses).
        self._client = (
            client
            if client is not None
            else genai.Client(
                api_key=config.api_key,
                http_options={"retry_options": {"attempts": 1}},
            )
        )

    def _build_kwargs(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        system_parts: list[str] = []
        if request.system_prompt:
            system_parts.append(request.system_prompt)

        steps: list[dict[str, Any]] = []
        for msg in request.messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            elif msg.role == "user":
                steps.append(
                    {
                        "type": "user_input",
                        "content": [{"type": "text", "text": msg.content}],
                    }
                )
            elif msg.role == "assistant":
                steps.append(
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": msg.content}],
                    }
                )

        kwargs: dict[str, Any] = {
            "model": request.model,
            "input": steps,
            "store": False,
            "stream": stream,
            "timeout": self._timeout_seconds,
        }
        if system_parts:
            kwargs["system_instruction"] = "\n\n".join(system_parts)

        generation_config: dict[str, Any] = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.max_tokens is not None:
            generation_config["max_output_tokens"] = request.max_tokens
        if generation_config:
            kwargs["generation_config"] = generation_config

        return kwargs

    async def generate(self, request: LLMRequest) -> LLMResponse:
        kwargs = self._build_kwargs(request, stream=False)

        async def _call() -> Any:
            try:
                return await self._client.aio.interactions.create(**kwargs)
            except Exception as exc:
                raise _map_gemini_error(exc) from exc

        interaction = await retry_async(
            _call,
            config=self._retry_config,
            operation_name="gemini.generate",
        )
        usage = _extract_gemini_usage(getattr(interaction, "usage", None))
        return LLMResponse(
            content=_extract_gemini_text(interaction),
            model=request.model,
            provider=self.name,
            usage=usage,
            finish_reason=getattr(interaction, "status", None),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        kwargs = self._build_kwargs(request, stream=True)

        async def _open_stream() -> Any:
            try:
                return await self._client.aio.interactions.create(**kwargs)
            except Exception as exc:
                raise _map_gemini_error(exc) from exc

        event_stream = await retry_async(
            _open_stream,
            config=self._retry_config,
            operation_name="gemini.stream",
        )

        final_usage = LLMUsage()
        finish_reason: str | None = None
        emitted_final = False

        try:
            async for event in event_stream:
                event_type = getattr(event, "event_type", None)
                if event_type == "step.delta":
                    delta = getattr(event, "delta", None)
                    if getattr(delta, "type", None) == "text":
                        text = getattr(delta, "text", None) or ""
                        if text:
                            yield LLMStreamChunk(delta_text=text)
                elif event_type == "interaction.completed":
                    interaction = getattr(event, "interaction", None)
                    final_usage = _extract_gemini_usage(getattr(interaction, "usage", None))
                    finish_reason = getattr(interaction, "status", "completed")
                    emitted_final = True
                    yield LLMStreamChunk(
                        is_final=True,
                        usage=final_usage,
                        finish_reason=finish_reason,
                    )
        except Exception as exc:
            raise _map_gemini_error(exc) from exc

        if not emitted_final:
            yield LLMStreamChunk(
                is_final=True,
                usage=final_usage,
                finish_reason=finish_reason,
            )

    async def aclose(self) -> None:
        close_fn = getattr(self._client, "aclose", None) or getattr(
            getattr(self._client, "aio", None), "aclose", None
        )
        if callable(close_fn):
            await close_fn()
