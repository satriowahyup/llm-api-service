"""Domain and provider exception hierarchy mapped to consistent HTTP error responses."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base application error carrying HTTP status, machine-readable code, and retry metadata."""

    status_code: int = 500
    code: str = "internal_error"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        retryable: bool | None = None,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        self.retry_after = retry_after
        self.details = details or {}


class SessionNotFoundError(AppError):
    status_code = 404
    code = "session_not_found"
    retryable = False


class ProviderNotConfiguredError(AppError):
    status_code = 400
    code = "provider_not_configured"
    retryable = False


class ProviderAuthError(AppError):
    status_code = 401
    code = "provider_auth_error"
    retryable = False


class ProviderBadRequestError(AppError):
    status_code = 400
    code = "provider_bad_request"
    retryable = False


class ProviderRateLimitError(AppError):
    status_code = 429
    code = "provider_rate_limit"
    retryable = True


class ProviderUnavailableError(AppError):
    status_code = 503
    code = "provider_unavailable"
    retryable = True


class ProviderTimeoutError(AppError):
    status_code = 504
    code = "provider_timeout"
    retryable = True


class ProviderUpstreamError(AppError):
    status_code = 502
    code = "provider_upstream_error"
    retryable = False
