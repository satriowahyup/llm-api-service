"""Async repository for session and message persistence and usage aggregation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from llm_api_service.db.models import MessageRecord, SessionRecord, utc_now


@dataclass(frozen=True, slots=True)
class SessionWithStats:
    """Session record paired with aggregated message counts, token usage, and USD cost."""

    session: SessionRecord
    message_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float


class ChatRepository:
    """Data-access layer for chat sessions and messages."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_session(
        self,
        *,
        provider: str,
        model: str,
        title: str | None = None,
        system_prompt: str | None = None,
    ) -> SessionRecord:
        record = SessionRecord(
            title=title,
            provider=provider,
            model=model,
            system_prompt=system_prompt,
        )
        self._db.add(record)
        await self._db.flush()
        await self._db.refresh(record)
        return record

    async def get_session(self, session_id: str) -> SessionRecord | None:
        stmt = select(SessionRecord).where(SessionRecord.id == session_id)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_session_with_messages(self, session_id: str) -> SessionRecord | None:
        stmt = (
            select(SessionRecord)
            .where(SessionRecord.id == session_id)
            .options(selectinload(SessionRecord.messages))
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_session_messages(self, session_id: str) -> list[MessageRecord]:
        stmt = (
            select(MessageRecord)
            .where(MessageRecord.session_id == session_id)
            .order_by(MessageRecord.created_at.asc())
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def add_message(
        self,
        *,
        session: SessionRecord,
        role: str,
        content: str,
        provider: str | None = None,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        ttft_ms: float | None = None,
        latency_ms: float | None = None,
        tokens_per_sec: float | None = None,
        update_session_provider: bool = False,
    ) -> MessageRecord:
        message = MessageRecord(
            session_id=session.id,
            role=role,
            content=content,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            ttft_ms=ttft_ms,
            latency_ms=latency_ms,
            tokens_per_sec=tokens_per_sec,
        )
        self._db.add(message)
        session.updated_at = utc_now()
        if update_session_provider and provider and model:
            session.provider = provider
            session.model = model
        await self._db.flush()
        await self._db.refresh(message)
        return message

    async def list_sessions_with_stats(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SessionWithStats], int]:
        """List sessions ordered by updated_at DESC with aggregated token usage and cost."""
        total_stmt = select(func.count(SessionRecord.id))
        total = int((await self._db.execute(total_stmt)).scalar_one() or 0)

        agg_stmt = (
            select(
                SessionRecord,
                func.count(MessageRecord.id).label("message_count"),
                func.coalesce(func.sum(MessageRecord.input_tokens), 0).label("total_input_tokens"),
                func.coalesce(func.sum(MessageRecord.output_tokens), 0).label(
                    "total_output_tokens"
                ),
                func.coalesce(func.sum(MessageRecord.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(MessageRecord.estimated_cost_usd), 0.0).label(
                    "total_cost_usd"
                ),
            )
            .outerjoin(MessageRecord, MessageRecord.session_id == SessionRecord.id)
            .group_by(SessionRecord.id)
            .order_by(SessionRecord.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._db.execute(agg_stmt)).all()
        items = [
            SessionWithStats(
                session=row[0],
                message_count=int(row[1]),
                total_input_tokens=int(row[2]),
                total_output_tokens=int(row[3]),
                total_tokens=int(row[4]),
                total_cost_usd=round(float(row[5]), 8),
            )
            for row in rows
        ]
        return items, total

    async def delete_session(self, session_id: str) -> bool:
        session = await self.get_session(session_id)
        if session is None:
            return False
        await self._db.delete(session)
        await self._db.flush()
        return True

    async def commit(self) -> None:
        await self._db.commit()
