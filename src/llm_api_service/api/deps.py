"""FastAPI dependency injection helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from llm_api_service.config import Settings
from llm_api_service.db.database import DatabaseManager
from llm_api_service.providers.registry import ProviderRegistry
from llm_api_service.services.chat_service import ChatService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db_manager(request: Request) -> DatabaseManager:
    return request.app.state.db_manager


def get_provider_registry(request: Request) -> ProviderRegistry:
    return request.app.state.provider_registry


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    db_manager: DatabaseManager = request.app.state.db_manager
    async for session in db_manager.get_session():
        yield session


def get_chat_service(request: Request) -> ChatService:
    return ChatService(
        settings=request.app.state.settings,
        db_manager=request.app.state.db_manager,
        provider_registry=request.app.state.provider_registry,
    )
