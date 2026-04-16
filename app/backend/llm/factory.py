"""Adapter factory — returns the configured LLM provider.

Supports three providers:
- `bedrock`    — AWS Bedrock (Mistral, Nova, Claude, Meta, etc.)
- `gemini`     — Google Gemini API (requires GOOGLE_API_KEY)
- `mock`       — deterministic test adapter (APP_ENV=test only)
"""

from __future__ import annotations

from functools import lru_cache

from app.backend.core.config import get_settings
from app.backend.core.logging import get_logger
from app.backend.llm.base import LLMAdapter

log = get_logger("llm.factory")


@lru_cache(maxsize=1)
def get_adapter() -> LLMAdapter:
    provider = get_settings().effective_provider
    if provider == "bedrock":
        from app.backend.llm.bedrock_adapter import BedrockAdapter

        log.info("llm.adapter.selected", provider="bedrock")
        return BedrockAdapter()

    if provider == "gemini":
        from app.backend.llm.gemini_adapter import GeminiAdapter

        log.info("llm.adapter.selected", provider="gemini")
        return GeminiAdapter()

    from app.backend.llm.mock_adapter import MockAdapter

    log.info("llm.adapter.selected", provider="mock")
    return MockAdapter()


@lru_cache(maxsize=1)
def get_judge_adapter() -> LLMAdapter:
    """Return a separate adapter for LLM-as-judge calls.

    When JUDGE_PROVIDER is set (e.g. "gemini"), judge calls route through
    a different provider than generation calls. This avoids self-evaluation
    bias and allows using a more reliable model for structured scoring.
    Falls back to the main adapter when JUDGE_PROVIDER is unset.
    """
    settings = get_settings()
    judge_provider = settings.judge_provider
    if not judge_provider:
        return get_adapter()

    if judge_provider == "gemini":
        from app.backend.llm.gemini_adapter import GeminiAdapter

        log.info("llm.judge_adapter.selected", provider="gemini")
        return GeminiAdapter()

    if judge_provider == "bedrock":
        from app.backend.llm.bedrock_adapter import BedrockAdapter

        log.info("llm.judge_adapter.selected", provider="bedrock")
        return BedrockAdapter()

    return get_adapter()


def reset_adapter_cache() -> None:
    get_adapter.cache_clear()
    get_judge_adapter.cache_clear()
