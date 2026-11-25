"""Session listing, detail inspection, and deletion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from llm_api_service.api.deps import get_db_session
from llm_api_service.core.exceptions import SessionNotFoundError
from llm_api_service.db.repository import ChatRepository
from llm_api_service.schemas.session import (
    MessageItem,
    SessionDetailResponse,
    SessionListResponse,
    SessionSummary,
)

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> SessionListResponse:
    repo = ChatRepository(db)
    rows, total = await repo.list_sessions_with_stats(limit=limit, offset=offset)
    items = [
        SessionSummary(
            id=row.session.id,
            title=row.session.title,
            provider=row.session.provider,
            model=row.session.model,
            system_prompt=row.session.system_prompt,
            message_count=row.message_count,
            total_input_tokens=row.total_input_tokens,
            total_output_tokens=row.total_output_tokens,
            total_tokens=row.total_tokens,
            total_cost_usd=row.total_cost_usd,
            created_at=row.session.created_at,
            updated_at=row.session.updated_at,
        )
        for row in rows
    ]
    return SessionListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> SessionDetailResponse:
    repo = ChatRepository(db)
    session = await repo.get_session_with_messages(session_id)
    if session is None:
        raise SessionNotFoundError(f"Session '{session_id}' was not found.")

    messages = [MessageItem.model_validate(msg) for msg in session.messages]
    total_in = sum(m.input_tokens for m in messages)
    total_out = sum(m.output_tokens for m in messages)
    total_tok = sum(m.total_tokens for m in messages)
    total_cost = round(sum(m.estimated_cost_usd for m in messages), 8)

    return SessionDetailResponse(
        id=session.id,
        title=session.title,
        provider=session.provider,
        model=session.model,
        system_prompt=session.system_prompt,
        message_count=len(messages),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_tokens=total_tok,
        total_cost_usd=total_cost,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=messages,
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    repo = ChatRepository(db)
    deleted = await repo.delete_session(session_id)
    if not deleted:
        raise SessionNotFoundError(f"Session '{session_id}' was not found.")
    await repo.commit()
    return Response(status_code=204)
