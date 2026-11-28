"""Provider registry managing adapter instantiation, caching, and graceful cleanup."""

from __future__ import annotations

from llm_api_service.config import ProviderName, Settings
from llm_api_service.core.exceptions import ProviderNotConfiguredError
from llm_api_service.core.retry import RetryConfig
from llm_api_service.providers.anthropic import AnthropicProvider
from llm_api_service.providers.base import BaseLLMProvider
from llm_api_service.providers.gemini import GeminiProvider
from llm_api_service.providers.openai_compat import OpenAICompatibleProvider


class ProviderRegistry:
    """Lazy cache and factory for configured multi-provider LLM adapters."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._retry_config = RetryConfig(
            max_retries=settings.llm_max_retries,
            base_delay=settings.llm_retry_base_delay,
            max_delay=settings.llm_retry_max_delay,
        )
        self._providers: dict[str, BaseLLMProvider] = {}

    def register(self, provider_name: ProviderName, provider: BaseLLMProvider) -> None:
        """Register a custom or mock provider instance (useful for tests)."""
        self._providers[provider_name] = provider

    def get(self, provider_name: ProviderName) -> BaseLLMProvider:
        """Return a cached provider adapter or instantiate it from Settings."""
        if provider_name in self._providers:
            return self._providers[provider_name]

        config = self._settings.get_provider_config(provider_name)
        if config.requires_api_key and not config.api_key:
            env_var = f"{provider_name.upper()}_API_KEY"
            raise ProviderNotConfiguredError(
                f"Provider '{provider_name}' is not configured. Set {env_var} in your environment."
            )

        provider: BaseLLMProvider
        if provider_name == "gemini":
            provider = GeminiProvider(
                config,
                retry_config=self._retry_config,
                timeout_seconds=self._settings.llm_timeout_seconds,
            )
        elif provider_name == "anthropic":
            provider = AnthropicProvider(
                config,
                retry_config=self._retry_config,
                timeout_seconds=self._settings.llm_timeout_seconds,
                connect_timeout_seconds=self._settings.llm_connect_timeout_seconds,
            )
        else:
            provider = OpenAICompatibleProvider(
                config,
                retry_config=self._retry_config,
                timeout_seconds=self._settings.llm_timeout_seconds,
                connect_timeout_seconds=self._settings.llm_connect_timeout_seconds,
            )

        self._providers[provider_name] = provider
        return provider

    async def aclose(self) -> None:
        """Close all initialized provider clients cleanly."""
        for provider in self._providers.values():
            await provider.aclose()
        self._providers.clear()
