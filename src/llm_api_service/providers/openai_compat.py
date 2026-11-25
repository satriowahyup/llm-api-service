"""OpenAI-compatible LLM provider adapter (OpenAI, DeepSeek, Groq, Ollama)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

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
from llm_api_service.core.retry import RetryConfig, parse_retry_after, retry_async
from llm_api_service.providers.base import (
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
)


def _extract_error_message(body_text: str, provider_name: str) -> str:
    try:
        payload = json.loads(body_text)
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if isinstance(err, str):
                return err
            if payload.get("message"):
                return str(payload["message"])
    except json.JSONDecodeError:
        pass
    return body_text[:300] or f"{provider_name} API request failed"


def _map_openai_http_error(
    response: httpx.Response,
    body_text: str,
    provider_name: str,
) -> AppError:
    status = response.status_code
    message = _extract_error_message(body_text, provider_name)
    retry_after = parse_retry_after(response.headers.get("retry-after"))

    if status in (401, 403):
        return ProviderAuthError(f"{provider_name} authentication failed: {message}")
    if status in (400, 404, 422):
        return ProviderBadRequestError(f"{provider_name} rejected request: {message}")
    if status == 429:
        return ProviderRateLimitError(
            f"{provider_name} rate limit exceeded: {message}",
            retry_after=retry_after,
        )
    if status in (500, 502, 503):
        return ProviderUnavailableError(
            f"{provider_name} service unavailable (HTTP {status}): {message}",
            retry_after=retry_after,
        )
    if status == 504:
        return ProviderTimeoutError(f"{provider_name} gateway timeout: {message}")
    return ProviderUpstreamError(f"{provider_name} unexpected error (HTTP {status}): {message}")


def _extract_usage(usage_raw: dict[str, Any] | None) -> LLMUsage:
    if not usage_raw:
        return LLMUsage()
    input_tokens = int(usage_raw.get("prompt_tokens") or usage_raw.get("input_tokens") or 0)
    output_tokens = int(usage_raw.get("completion_tokens") or usage_raw.get("output_tokens") or 0)
    total_tokens = int(usage_raw.get("total_tokens") or (input_tokens + output_tokens))
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


class OpenAICompatibleProvider:
    """Adapter for OpenAI Chat Completions wire protocol (OpenAI, DeepSeek, Groq, Ollama)."""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        retry_config: RetryConfig,
        timeout_seconds: float = 60.0,
        connect_timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name: str = config.name
        self._config = config
        self._retry_config = retry_config
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds)
        )

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._config.api_key:
            headers["authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def _endpoint(self) -> str:
        base = (self._config.base_url or "https://api.openai.com/v1").rstrip("/")
        return f"{base}/chat/completions"

    def _build_payload(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "stream": stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def generate(self, request: LLMRequest) -> LLMResponse:
        url = self._endpoint()
        payload = self._build_payload(request, stream=False)

        async def _call() -> dict[str, Any]:
            try:
                response = await self._client.post(url, headers=self._headers(), json=payload)
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(f"{self.name} request timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(f"{self.name} network error: {exc}") from exc

            if response.status_code >= 400:
                raise _map_openai_http_error(response, response.text, self.name)
            return response.json()

        data = await retry_async(
            _call,
            config=self._retry_config,
            operation_name=f"{self.name}.generate",
        )

        choices = data.get("choices") or []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message") or {}
        content = str(message.get("content") or "")

        return LLMResponse(
            content=content,
            model=str(data.get("model") or request.model),
            provider=self.name,
            usage=_extract_usage(data.get("usage")),
            finish_reason=first_choice.get("finish_reason"),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        url = self._endpoint()
        payload = self._build_payload(request, stream=True)

        async def _open_response() -> httpx.Response:
            req = self._client.build_request("POST", url, headers=self._headers(), json=payload)
            try:
                response = await self._client.send(req, stream=True)
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(f"{self.name} stream timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(f"{self.name} stream network error: {exc}") from exc

            if response.status_code >= 400:
                body_bytes = await response.aread()
                await response.aclose()
                raise _map_openai_http_error(
                    response,
                    body_bytes.decode("utf-8", errors="replace"),
                    self.name,
                )
            return response

        response = await retry_async(
            _open_response,
            config=self._retry_config,
            operation_name=f"{self.name}.stream",
        )

        final_usage = LLMUsage()
        finish_reason: str | None = None

        try:
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line.removeprefix("data:").strip()
                if data_str == "[DONE]":
                    break

                chunk_data = json.loads(data_str)
                if chunk_data.get("usage"):
                    final_usage = _extract_usage(chunk_data["usage"])

                choices = chunk_data.get("choices") or []
                if not choices:
                    continue
                first = choices[0]
                if first.get("finish_reason"):
                    finish_reason = str(first["finish_reason"])
                delta = first.get("delta") or {}
                delta_text = delta.get("content")
                if delta_text:
                    yield LLMStreamChunk(delta_text=str(delta_text))
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"{self.name} stream interrupted by timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self.name} stream connection lost: {exc}") from exc
        finally:
            await response.aclose()

        yield LLMStreamChunk(
            is_final=True,
            usage=final_usage,
            finish_reason=finish_reason,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
