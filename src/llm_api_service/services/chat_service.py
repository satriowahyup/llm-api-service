"""Chat orchestration: 3-tier provider resolution, SSE streaming, metrics, and persistence."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, cast

from llm_api_service.config import ProviderName, Settings
from llm_api_service.core.exceptions import AppError, SessionNotFoundError
from llm_api_service.core.logging import request_id_ctx
from llm_api_service.core.metrics import GenerationMetricsTracker
from llm_api_service.core.pricing import estimate_cost_usd
from llm_api_service.db.database import DatabaseManager
from llm_api_service.db.models import SessionRecord
from llm_api_service.db.repository import ChatRepository
from llm_api_service.providers.base import BaseLLMProvider, ChatMessage, LLMRequest, LLMUsage
from llm_api_service.providers.registry import ProviderRegistry
from llm_api_service.schemas.chat import ChatRequest, ChatResponse, LatencyMetrics, UsageStats

logger = logging.getLogger(__name__)


def _derive_session_title(message: str, max_len: int = 80) -> str:
    cleaned = " ".join(message.strip().split())
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[: max_len - 3].rstrip()}..."


def format_sse_event(event: str, payload: dict[str, Any]) -> str:
    """Format a Server-Sent Events (SSE) frame."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@dataclass(slots=True)
class PreparedTurn:
    """Validated chat turn ready for LLM execution without holding an open DB transaction."""

    session_id: str
    provider_name: ProviderName
    model: str
    provider: BaseLLMProvider
    llm_request: LLMRequest


class ChatService:
    """Coordinates session persistence, provider selection, metrics, cost tracking, and SSE."""

    def __init__(
        self,
        *,
        settings: Settings,
        db_manager: DatabaseManager,
        provider_registry: ProviderRegistry,
    ) -> None:
        self._settings = settings
        self._db_manager = db_manager
        self._registry = provider_registry

    def resolve_provider_and_model(
        self,
        request: ChatRequest,
        session: SessionRecord | None,
    ) -> tuple[ProviderName, str]:
        """Resolve (provider, model) using 3-tier precedence with mid-session switch safeguard."""
        if session is None:
            provider: ProviderName = request.provider or self._settings.default_provider
            model = request.model or self._settings.get_provider_config(provider).default_model
            return provider, model

        session_provider = cast(ProviderName, session.provider)
        provider = request.provider or session_provider

        if request.model is not None:
            model = request.model
        elif provider != session_provider:
            # Safeguard: never forward the previous provider's model name to a different provider.
            model = self._settings.get_provider_config(provider).default_model
        else:
            model = session.model

        return provider, model

    async def prepare_turn(self, payload: ChatRequest) -> PreparedTurn:
        """Validate session & provider, persist the user turn, and release the DB lock."""
        async with self._db_manager.session_factory() as db:
            repo = ChatRepository(db)
            existing_session: SessionRecord | None = None
            if payload.session_id is not None:
                existing_session = await repo.get_session(payload.session_id)
                if existing_session is None:
                    raise SessionNotFoundError(f"Session '{payload.session_id}' was not found.")

            provider_name, model = self.resolve_provider_and_model(payload, existing_session)
            # Validate provider configuration before writing to DB
            provider = self._registry.get(provider_name)

            if existing_session is None:
                session = await repo.create_session(
                    provider=provider_name,
                    model=model,
                    title=_derive_session_title(payload.message),
                    system_prompt=payload.system_prompt,
                )
                history_records = []
            else:
                session = existing_session
                history_records = await repo.get_session_messages(session.id)

            await repo.add_message(
                session=session,
                role="user",
                content=payload.message,
            )
            await repo.commit()

            effective_system_prompt = (
                payload.system_prompt
                if payload.system_prompt is not None
                else session.system_prompt
            )
            messages: list[ChatMessage] = [
                ChatMessage(
                    role=cast(Literal["system", "user", "assistant"], rec.role),
                    content=rec.content,
                )
                for rec in history_records
            ]
            messages.append(ChatMessage(role="user", content=payload.message))

            llm_request = LLMRequest(
                model=model,
                messages=messages,
                system_prompt=effective_system_prompt,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
            )
            return PreparedTurn(
                session_id=session.id,
                provider_name=provider_name,
                model=model,
                provider=provider,
                llm_request=llm_request,
            )

    async def _persist_assistant_message(
        self,
        *,
        session_id: str,
        provider_name: str,
        model: str,
        content: str,
        usage: LLMUsage,
        cost_usd: float,
        ttft_ms: float | None,
        latency_ms: float,
        tokens_per_sec: float | None,
    ) -> str:
        async with self._db_manager.session_factory() as db:
            repo = ChatRepository(db)
            session = await repo.get_session(session_id)
            if session is None:
                raise SessionNotFoundError(f"Session '{session_id}' no longer exists.")

            msg = await repo.add_message(
                session=session,
                role="assistant",
                content=content,
                provider=provider_name,
                model=model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                estimated_cost_usd=cost_usd,
                ttft_ms=ttft_ms,
                latency_ms=latency_ms,
                tokens_per_sec=tokens_per_sec,
                update_session_provider=True,
            )
            await repo.commit()
            return msg.id

    async def chat(self, payload: ChatRequest) -> ChatResponse:
        """Execute a non-streaming chat turn end-to-end."""
        turn = await self.prepare_turn(payload)
        tracker = GenerationMetricsTracker()

        llm_response = await turn.provider.generate(turn.llm_request)
        metrics = tracker.finish(output_tokens=llm_response.usage.output_tokens)
        cost_usd = estimate_cost_usd(
            provider=turn.provider_name,
            model=turn.model,
            input_tokens=llm_response.usage.input_tokens,
            output_tokens=llm_response.usage.output_tokens,
        )

        message_id = await self._persist_assistant_message(
            session_id=turn.session_id,
            provider_name=turn.provider_name,
            model=turn.model,
            content=llm_response.content,
            usage=llm_response.usage,
            cost_usd=cost_usd,
            ttft_ms=metrics.ttft_ms,
            latency_ms=metrics.latency_ms,
            tokens_per_sec=metrics.tokens_per_sec,
        )

        logger.info(
            "Chat completion finished",
            extra={
                "session_id": turn.session_id,
                "message_id": message_id,
                "provider": turn.provider_name,
                "model": turn.model,
                "input_tokens": llm_response.usage.input_tokens,
                "output_tokens": llm_response.usage.output_tokens,
                "estimated_cost_usd": cost_usd,
                "latency_ms": metrics.latency_ms,
                "tokens_per_sec": metrics.tokens_per_sec,
            },
        )

        return ChatResponse(
            session_id=turn.session_id,
            message_id=message_id,
            provider=turn.provider_name,
            model=turn.model,
            content=llm_response.content,
            usage=UsageStats(
                input_tokens=llm_response.usage.input_tokens,
                output_tokens=llm_response.usage.output_tokens,
                total_tokens=llm_response.usage.total_tokens,
                estimated_cost_usd=cost_usd,
            ),
            metrics=LatencyMetrics(
                ttft_ms=metrics.ttft_ms,
                latency_ms=metrics.latency_ms,
                tokens_per_sec=metrics.tokens_per_sec,
            ),
        )

    async def stream_turn(self, turn: PreparedTurn) -> AsyncIterator[str]:
        """Stream SSE events for a prepared turn and persist metrics once completed."""
        yield format_sse_event(
            "meta",
            {
                "session_id": turn.session_id,
                "provider": turn.provider_name,
                "model": turn.model,
            },
        )

        tracker = GenerationMetricsTracker()
        collected_parts: list[str] = []
        final_usage = LLMUsage()

        try:
            async for chunk in turn.provider.stream(turn.llm_request):
                if chunk.delta_text:
                    tracker.mark_first_token()
                    collected_parts.append(chunk.delta_text)
                    yield format_sse_event("delta", {"text": chunk.delta_text})
                if chunk.is_final and chunk.usage is not None:
                    final_usage = chunk.usage

            full_content = "".join(collected_parts)
            metrics = tracker.finish(output_tokens=final_usage.output_tokens)
            cost_usd = estimate_cost_usd(
                provider=turn.provider_name,
                model=turn.model,
                input_tokens=final_usage.input_tokens,
                output_tokens=final_usage.output_tokens,
            )

            message_id = await self._persist_assistant_message(
                session_id=turn.session_id,
                provider_name=turn.provider_name,
                model=turn.model,
                content=full_content,
                usage=final_usage,
                cost_usd=cost_usd,
                ttft_ms=metrics.ttft_ms,
                latency_ms=metrics.latency_ms,
                tokens_per_sec=metrics.tokens_per_sec,
            )

            logger.info(
                "Chat stream finished",
                extra={
                    "session_id": turn.session_id,
                    "message_id": message_id,
                    "provider": turn.provider_name,
                    "model": turn.model,
                    "input_tokens": final_usage.input_tokens,
                    "output_tokens": final_usage.output_tokens,
                    "estimated_cost_usd": cost_usd,
                    "ttft_ms": metrics.ttft_ms,
                    "latency_ms": metrics.latency_ms,
                    "tokens_per_sec": metrics.tokens_per_sec,
                },
            )

            yield format_sse_event(
                "done",
                {
                    "session_id": turn.session_id,
                    "message_id": message_id,
                    "provider": turn.provider_name,
                    "model": turn.model,
                    "usage": {
                        "input_tokens": final_usage.input_tokens,
                        "output_tokens": final_usage.output_tokens,
                        "total_tokens": final_usage.total_tokens,
                        "estimated_cost_usd": cost_usd,
                    },
                    "metrics": {
                        "ttft_ms": metrics.ttft_ms,
                        "latency_ms": metrics.latency_ms,
                        "tokens_per_sec": metrics.tokens_per_sec,
                    },
                },
            )
        except asyncio.CancelledError:
            logger.info(
                "Client disconnected during SSE stream",
                extra={
                    "session_id": turn.session_id,
                    "provider": turn.provider_name,
                    "model": turn.model,
                },
            )
            raise
        except AppError as exc:
            logger.warning(
                "Provider error during SSE stream",
                extra={
                    "session_id": turn.session_id,
                    "provider": turn.provider_name,
                    "model": turn.model,
                    "error_code": exc.code,
                },
            )
            yield format_sse_event(
                "error",
                {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": request_id_ctx.get(),
                },
            )
        except Exception:
            logger.exception(
                "Unexpected error during SSE stream",
                extra={
                    "session_id": turn.session_id,
                    "provider": turn.provider_name,
                    "model": turn.model,
                },
            )
            yield format_sse_event(
                "error",
                {
                    "code": "internal_error",
                    "message": "An unexpected error occurred while streaming the response.",
                    "request_id": request_id_ctx.get(),
                },
            )
