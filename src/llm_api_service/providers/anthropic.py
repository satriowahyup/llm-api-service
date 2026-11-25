"""Anthropic Claude LLM provider adapter using Messages API over httpx.AsyncClient."""

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


def _extract_error_message(body_text: str) -> str:
    try:
        payload = json.loads(body_text)
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if payload.get("message"):
                return str(payload["message"])
    except json.JSONDecodeError:
        pass
    return body_text[:300] or "Anthropic API request failed"


def _map_anthropic_http_error(response: httpx.Response, body_text: str) -> AppError:
    status = response.status_code
    message = _extract_error_message(body_text)
    retry_after = parse_retry_after(response.headers.get("retry-after"))

    if status in (401, 403):
        return ProviderAuthError(f"Anthropic authentication failed: {message}")
    if status in (400, 404, 422):
        return ProviderBadRequestError(f"Anthropic rejected request: {message}")
    if status == 429:
        return ProviderRateLimitError(
            f"Anthropic rate limit exceeded: {message}",
            retry_after=retry_after,
        )
    # Anthropic uses HTTP 529 (overloaded_error) for temporary capacity overload
    if status in (500, 502, 503, 529):
        return ProviderUnavailableError(
            f"Anthropic service unavailable (HTTP {status}): {message}",
            retry_after=retry_after,
        )
    if status == 504:
        return ProviderTimeoutError(f"Anthropic gateway timeout: {message}")
    return ProviderUpstreamError(f"Anthropic unexpected error (HTTP {status}): {message}")


class AnthropicProvider:
    """Adapter for Anthropic Messages API (POST /v1/messages) with SSE streaming."""

    name: str = "anthropic"

    def __init__(
        self,
        config: ProviderConfig,
        *,
        retry_config: RetryConfig,
        timeout_seconds: float = 60.0,
        connect_timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._retry_config = retry_config
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds)
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "anthropic-version": self._config.api_version or "2023-06-01",
        }
        if self._config.api_key:
            headers["x-api-key"] = self._config.api_key
        return headers

    def _endpoint(self) -> str:
        base = (self._config.base_url or "https://api.anthropic.com").rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"

    def _build_payload(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        system_parts: list[str] = []
        if request.system_prompt:
            system_parts.append(request.system_prompt)

        messages: list[dict[str, str]] = []
        for msg in request.messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            else:
                messages.append({"role": msg.role, "content": msg.content})

        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens or self._config.default_max_tokens,
            "messages": messages,
            "stream": stream,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload

    async def generate(self, request: LLMRequest) -> LLMResponse:
        url = self._endpoint()
        payload = self._build_payload(request, stream=False)

        async def _call() -> dict[str, Any]:
            try:
                response = await self._client.post(url, headers=self._headers(), json=payload)
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(f"Anthropic request timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(f"Anthropic network error: {exc}") from exc

            if response.status_code >= 400:
                raise _map_anthropic_http_error(response, response.text)
            return response.json()

        data = await retry_async(
            _call,
            config=self._retry_config,
            operation_name="anthropic.generate",
        )

        text_parts = [
            str(block.get("text", ""))
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        usage_raw = data.get("usage") or {}
        input_tokens = int(usage_raw.get("input_tokens") or 0)
        output_tokens = int(usage_raw.get("output_tokens") or 0)

        return LLMResponse(
            content="".join(text_parts),
            model=str(data.get("model") or request.model),
            provider=self.name,
            usage=LLMUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            finish_reason=data.get("stop_reason"),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        url = self._endpoint()
        payload = self._build_payload(request, stream=True)

        async def _open_response() -> httpx.Response:
            req = self._client.build_request("POST", url, headers=self._headers(), json=payload)
            try:
                response = await self._client.send(req, stream=True)
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(f"Anthropic stream timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(f"Anthropic stream network error: {exc}") from exc

            if response.status_code >= 400:
                body_bytes = await response.aread()
                await response.aclose()
                raise _map_anthropic_http_error(
                    response,
                    body_bytes.decode("utf-8", errors="replace"),
                )
            return response

        response = await retry_async(
            _open_response,
            config=self._retry_config,
            operation_name="anthropic.stream",
        )

        input_tokens = 0
        output_tokens = 0
        finish_reason: str | None = None
        current_event: str | None = None

        try:
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line:
                    current_event = None
                    continue
                if line.startswith("event:"):
                    current_event = line.removeprefix("event:").strip()
                    continue
                if not line.startswith("data:"):
                    continue

                data_str = line.removeprefix("data:").strip()
                if not data_str:
                    continue

                event_data = json.loads(data_str)
                event_type = event_data.get("type") or current_event

                if event_type == "ping":
                    continue
                if event_type == "message_start":
                    msg_usage = (event_data.get("message") or {}).get("usage") or {}
                    input_tokens = int(msg_usage.get("input_tokens") or 0)
                    output_tokens = int(msg_usage.get("output_tokens") or output_tokens)
                elif event_type == "content_block_delta":
                    delta = event_data.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = str(delta.get("text") or "")
                        if text:
                            yield LLMStreamChunk(delta_text=text)
                elif event_type == "message_delta":
                    delta = event_data.get("delta") or {}
                    if delta.get("stop_reason"):
                        finish_reason = str(delta["stop_reason"])
                    delta_usage = event_data.get("usage") or {}
                    if "output_tokens" in delta_usage:
                        output_tokens = int(delta_usage["output_tokens"] or 0)
                elif event_type == "error":
                    err = event_data.get("error") or {}
                    err_type = str(err.get("type") or "api_error")
                    err_msg = str(err.get("message") or "Anthropic stream error")
                    if err_type == "overloaded_error":
                        raise ProviderUnavailableError(f"Anthropic overloaded: {err_msg}")
                    if err_type == "rate_limit_error":
                        raise ProviderRateLimitError(f"Anthropic rate limit: {err_msg}")
                    raise ProviderUpstreamError(f"Anthropic stream error: {err_msg}")
                elif event_type == "message_stop":
                    break
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Anthropic stream interrupted by timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Anthropic stream connection lost: {exc}") from exc
        finally:
            await response.aclose()

        yield LLMStreamChunk(
            is_final=True,
            usage=LLMUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            finish_reason=finish_reason,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
