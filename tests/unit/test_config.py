"""Tests for Settings.validate_for_runtime, effective_provider, and CORS parsing."""

from __future__ import annotations

import os

import pytest

from app.backend.core.config import Settings, get_settings


def _make_settings(**overrides) -> Settings:
    # Build without re-reading .env so tests stay hermetic.
    env_vars = {
        "APP_ENV": overrides.get("app_env", "development"),
        "CORS_ALLOW_ORIGINS": overrides.get("cors", "http://localhost:8000"),
        "LLM_PROVIDER": overrides.get("provider", "mock"),
        "GOOGLE_API_KEY": overrides.get("key", "") or "",
    }
    original = {k: os.environ.get(k) for k in env_vars}
    os.environ.update(env_vars)
    get_settings.cache_clear()
    try:
        return Settings()
    finally:
        for k, v in original.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()


def test_cors_list_parsing():
    s = _make_settings(cors="http://a.example, http://b.example")
    assert s.cors_origins_list == ["http://a.example", "http://b.example"]


def test_effective_provider_gemini_with_key():
    s = _make_settings(provider="gemini", key="AIza-test")
    assert s.effective_provider == "gemini"


def test_effective_provider_explicit_mock():
    s = _make_settings(provider="mock", key="")
    assert s.effective_provider == "mock"


def test_effective_provider_test_env_falls_back_to_mock():
    """In APP_ENV=test, missing key silently falls back to mock (for CI)."""
    s = _make_settings(app_env="test", provider="gemini", key="")
    assert s.effective_provider == "mock"


def test_effective_provider_dev_no_key_raises():
    """In non-test env, missing key raises RuntimeError — not a silent fallback."""
    s = _make_settings(app_env="development", provider="gemini", key="")
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY is not set"):
        _ = s.effective_provider


def test_validate_production_refuses_wildcard_cors():
    s = _make_settings(
        app_env="production", provider="bedrock", cors="*"
    )
    with pytest.raises(RuntimeError):
        s.validate_for_runtime()


def test_validate_dev_bedrock_is_ok():
    s = _make_settings(app_env="development", provider="bedrock")
    s.validate_for_runtime()
