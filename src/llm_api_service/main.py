"""FastAPI application factory, lifespan management, and observability middleware."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from llm_api_service.api.errors import register_exception_handlers
from llm_api_service.api.routes import chat, health, sessions
from llm_api_service.config import Settings, get_settings
from llm_api_service.core.logging import configure_logging, request_id_ctx
from llm_api_service.db.database import DatabaseManager
from llm_api_service.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    db_manager: DatabaseManager | None = None,
    provider_registry: ProviderRegistry | None = None,
) -> FastAPI:
    """Create and wire a configured FastAPI application instance."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    resolved_db = db_manager or DatabaseManager(resolved_settings)
    resolved_registry = provider_registry or ProviderRegistry(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = resolved_settings
        application.state.db_manager = resolved_db
        application.state.provider_registry = resolved_registry

        if resolved_settings.db_auto_create_tables:
            await resolved_db.init_tables()

        logger.info(
            "Service started",
            extra={
                "app_env": resolved_settings.app_env,
                "db_dialect": resolved_db.dialect,
                "default_provider": resolved_settings.default_provider,
            },
        )
        try:
            yield
        finally:
            await resolved_registry.aclose()
            await resolved_db.dispose()
            logger.info("Service shut down cleanly")

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=(
            "Production-grade multi-provider async LLM REST & SSE API service "
            "(Google Gemini, Anthropic Claude, OpenAI, DeepSeek, Groq, Ollama)."
        ),
        lifespan=lifespan,
    )

    app.state.settings = resolved_settings
    app.state.db_manager = resolved_db
    app.state.provider_registry = resolved_registry

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next: Any) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(req_id)
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Latency-Ms"] = str(elapsed_ms)
        return response

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(sessions.router)
    return app


app = create_app()


def run() -> None:
    """Launch Uvicorn server using configured host and port."""
    settings = get_settings()
    uvicorn.run(
        "llm_api_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.app_env == "development",
    )
