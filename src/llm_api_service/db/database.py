"""Dialect-aware async database engine and session lifecycle management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from llm_api_service.config import Settings
from llm_api_service.db.models import Base


def _is_sqlite_memory(database_url: str) -> bool:
    url = make_url(database_url)
    return url.get_backend_name() == "sqlite" and (not url.database or url.database == ":memory:")


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    db_path = Path(url.database)
    db_path.parent.mkdir(parents=True, exist_ok=True)


def create_async_db_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_size: int = 10,
    max_overflow: int = 20,
) -> AsyncEngine:
    """Create a dialect-aware SQLAlchemy AsyncEngine for SQLite or PostgreSQL."""
    url = make_url(database_url)
    backend = url.get_backend_name()

    engine_kwargs: dict[str, Any] = {"echo": echo}

    if backend == "sqlite":
        is_memory = _is_sqlite_memory(database_url)
        if not is_memory:
            _ensure_sqlite_parent_dir(database_url)
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if is_memory:
            engine_kwargs["poolclass"] = StaticPool

        engine = create_async_engine(database_url, **engine_kwargs)

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            if not is_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return engine

    # PostgreSQL (asyncpg / psycopg) production pooling settings
    engine_kwargs.update(
        {
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_pre_ping": True,
        }
    )
    return create_async_engine(database_url, **engine_kwargs)


class DatabaseManager:
    """Manages AsyncEngine, session factory, schema initialization, and health checks."""

    def __init__(self, settings: Settings) -> None:
        self.database_url = settings.database_url
        self.dialect = settings.db_dialect
        self.engine = create_async_db_engine(
            settings.database_url,
            echo=settings.db_echo,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def init_tables(self) -> None:
        """Create tables if they do not exist (used for local dev/testing)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def health_check(self) -> bool:
        """Execute lightweight SELECT 1 probe against the configured database."""
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def get_session(self) -> AsyncIterator[AsyncSession]:
        """Yield an AsyncSession for request-scoped dependency injection."""
        async with self.session_factory() as session:
            yield session

    async def dispose(self) -> None:
        """Close all database connections gracefully."""
        await self.engine.dispose()
