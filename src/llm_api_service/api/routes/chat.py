"""Chat completion and SSE streaming endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from llm_api_service.api.deps import get_chat_service
from llm_api_service.schemas.chat import ChatRequest, ChatResponse
from llm_api_service.services.chat_service import ChatService

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def create_chat_completion(
    payload: ChatRequest,
    response: Response,
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    result = await chat_service.chat(payload)
    response.headers["X-Provider"] = result.provider
    response.headers["X-Model"] = result.model
    return result


@router.post("/chat/stream")
async def stream_chat_completion(
    payload: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    # Validate session & provider configuration before opening SSE response
    turn = await chat_service.prepare_turn(payload)
    return StreamingResponse(
        chat_service.stream_turn(turn),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Provider": turn.provider_name,
            "X-Model": turn.model,
        },
    )
