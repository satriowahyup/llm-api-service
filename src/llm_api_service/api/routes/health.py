"""Health and readiness probe route."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from llm_api_service.api.deps import get_app_settings, get_db_manager
from llm_api_service.config import Settings
from llm_api_service.db.database import DatabaseManager
from llm_api_service.schemas.chat import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(
    settings: Settings = Depends(get_app_settings),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> HealthResponse | JSONResponse:
    db_ok = await db_manager.health_check()
    default_cfg = settings.get_provider_config(settings.default_provider)
    payload = HealthResponse(
        status="ok" if db_ok else "degraded",
        version=settings.app_version,
        database="connected" if db_ok else "disconnected",
        database_dialect=db_manager.dialect,
        default_provider=settings.default_provider,
        default_model=default_cfg.default_model,
    )
    if not db_ok:
        return JSONResponse(status_code=503, content=payload.model_dump())
    return payload
