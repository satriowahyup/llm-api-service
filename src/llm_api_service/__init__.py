"""llm-api-service package entry point."""

from __future__ import annotations

from llm_api_service.main import create_app, run


def main() -> None:
    """CLI entrypoint to run the FastAPI server."""
    run()


__all__ = ["create_app", "main", "run"]
