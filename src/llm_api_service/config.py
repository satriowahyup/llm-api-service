"""Application configuration powered by Pydantic Settings."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["gemini", "anthropic", "openai", "deepseek", "groq", "ollama"]
SUPPORTED_PROVIDERS: tuple[ProviderName, ...] = (
    "gemini",
    "anthropic",
    "openai",
    "deepseek",
    "groq",
    "ollama",
)


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Resolved runtime configuration for a single LLM provider."""

    name: ProviderName
    api_key: str | None
    base_url: str | None
    default_model: str
    default_max_tokens: int
    api_version: str | None = None
    requires_api_key: bool = True


class Settings(BaseSettings):
    """Environment-driven application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "llm-api-service"
    app_version: str = "0.1.0"
    app_env: str = "development"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # Database (dual-backend: SQLite default, PostgreSQL production)
    database_url: str = "sqlite+aiosqlite:///./data/llm_service.db"
    db_echo: bool = False
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=20, ge=0)
    db_auto_create_tables: bool = True

    # Default LLM provider
    default_provider: ProviderName = "gemini"
    default_max_tokens: int = Field(default=1024, ge=1)

    # Google Gemini (default)
    gemini_api_key: SecretStr | None = None
    gemini_default_model: str = "gemini-4-hydrogen"

    # Anthropic Claude
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_version: str = "2023-06-01"
    anthropic_default_model: str = "claude-sonnet-4-6"
    anthropic_default_max_tokens: int = Field(default=1024, ge=1)

    # OpenAI
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_default_model: str = "gpt-4o-mini"

    # DeepSeek
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_default_model: str = "deepseek-chat"

    # Groq
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_default_model: str = "llama-3.3-70b-versatile"

    # Ollama (local OpenAI-compatible)
    ollama_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_default_model: str = "llama3.2"

    # Resilience & timeouts
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0, le=10)
    llm_retry_base_delay: float = Field(default=0.5, gt=0)
    llm_retry_max_delay: float = Field(default=8.0, gt=0)

    @property
    def db_dialect(self) -> str:
        """Return normalized database dialect name."""
        lower = self.database_url.lower()
        if lower.startswith("sqlite"):
            return "sqlite"
        if lower.startswith("postgresql") or lower.startswith("postgres"):
            return "postgresql"
        return lower.split(":", 1)[0]

    def _secret_value(self, secret: SecretStr | None) -> str | None:
        if secret is None:
            return None
        value = secret.get_secret_value().strip()
        return value or None

    def get_provider_config(self, provider: ProviderName) -> ProviderConfig:
        """Resolve credentials, endpoint, and default model for a given provider."""
        if provider == "gemini":
            return ProviderConfig(
                name="gemini",
                api_key=self._secret_value(self.gemini_api_key),
                base_url=None,
                default_model=self.gemini_default_model,
                default_max_tokens=self.default_max_tokens,
            )
        if provider == "anthropic":
            return ProviderConfig(
                name="anthropic",
                api_key=self._secret_value(self.anthropic_api_key),
                base_url=self.anthropic_base_url.rstrip("/"),
                default_model=self.anthropic_default_model,
                default_max_tokens=self.anthropic_default_max_tokens,
                api_version=self.anthropic_version,
            )
        if provider == "openai":
            return ProviderConfig(
                name="openai",
                api_key=self._secret_value(self.openai_api_key),
                base_url=self.openai_base_url.rstrip("/"),
                default_model=self.openai_default_model,
                default_max_tokens=self.default_max_tokens,
            )
        if provider == "deepseek":
            return ProviderConfig(
                name="deepseek",
                api_key=self._secret_value(self.deepseek_api_key),
                base_url=self.deepseek_base_url.rstrip("/"),
                default_model=self.deepseek_default_model,
                default_max_tokens=self.default_max_tokens,
            )
        if provider == "groq":
            return ProviderConfig(
                name="groq",
                api_key=self._secret_value(self.groq_api_key),
                base_url=self.groq_base_url.rstrip("/"),
                default_model=self.groq_default_model,
                default_max_tokens=self.default_max_tokens,
            )
        if provider == "ollama":
            return ProviderConfig(
                name="ollama",
                api_key=self._secret_value(self.ollama_api_key),
                base_url=self.ollama_base_url.rstrip("/"),
                default_model=self.ollama_default_model,
                default_max_tokens=self.default_max_tokens,
                requires_api_key=False,
            )
        raise ValueError(f"Unsupported provider: {provider}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
