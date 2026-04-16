"""Tests for LLM adapter helpers — Bedrock body/response parsing, Gemini config, factory branches."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.backend.llm.base import LLMMessage, LLMRequest, LLMResponse


# ── Bedrock helpers ────────────────────────────────────────────────────

def _req(model="mistral.mistral-large-3", **kw):
    return LLMRequest(
        model=model, system="sys", messages=[LLMMessage(role="user", content="hi")], **kw
    )


class TestBedrockHelpers:
    def test_is_anthropic(self):
        from app.backend.llm.bedrock_adapter import _is_anthropic
        assert _is_anthropic("anthropic.claude-3") is True
        assert _is_anthropic("mistral.large") is False

    def test_build_body_anthropic(self):
        from app.backend.llm.bedrock_adapter import _build_body
        body = _build_body(_req(model="anthropic.claude-3-sonnet"))
        assert "anthropic_version" in body
        assert body["messages"][0]["role"] == "user"

    def test_build_body_mistral(self):
        from app.backend.llm.bedrock_adapter import _build_body
        body = _build_body(_req(model="mistral.large"))
        assert "anthropic_version" not in body
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["content"] == "hi"

    def test_parse_response_anthropic(self):
        from app.backend.llm.bedrock_adapter import _parse_response
        body = {"content": [{"type": "text", "text": "hello world"}]}
        assert _parse_response("anthropic.claude-3", body) == "hello world"

    def test_parse_response_mistral(self):
        from app.backend.llm.bedrock_adapter import _parse_response
        body = {"choices": [{"message": {"content": "hello"}}]}
        assert _parse_response("mistral.large", body) == "hello"

    def test_parse_response_nova(self):
        from app.backend.llm.bedrock_adapter import _parse_response
        body = {"output": {"message": {"content": [{"text": "nova reply"}]}}}
        assert _parse_response("amazon.nova", body) == "nova reply"

    def test_parse_response_meta(self):
        from app.backend.llm.bedrock_adapter import _parse_response
        body = {"generation": "meta reply"}
        assert _parse_response("meta.llama", body) == "meta reply"

    def test_parse_response_fallback(self):
        from app.backend.llm.bedrock_adapter import _parse_response
        body = {"unknown": "data"}
        result = _parse_response("unknown.model", body)
        assert "unknown" in result  # JSON fallback

    def test_extract_usage(self):
        from app.backend.llm.bedrock_adapter import _extract_usage
        usage = _extract_usage("m", {"usage": {"input_tokens": 10, "output_tokens": 5}})
        assert usage == {"input_tokens": 10, "output_tokens": 5}

    def test_extract_usage_empty(self):
        from app.backend.llm.bedrock_adapter import _extract_usage
        usage = _extract_usage("m", {})
        assert usage == {"input_tokens": 0, "output_tokens": 0}


class TestBedrockAdapter:
    @pytest.mark.asyncio
    async def test_complete_success(self):
        from app.backend.llm.bedrock_adapter import BedrockAdapter
        adapter = BedrockAdapter.__new__(BedrockAdapter)
        adapter._client = MagicMock()
        adapter._region = "us-east-1"

        fake_body = {"choices": [{"message": {"content": '{"answer":"ok"}'}}], "usage": {"input_tokens": 5, "output_tokens": 3}}
        adapter._invoke = MagicMock(return_value=fake_body)

        with patch("app.backend.llm.bedrock_adapter._parse_response", return_value='{"answer":"ok"}'), \
             patch("app.backend.llm.bedrock_adapter._extract_usage", return_value={"input_tokens": 5, "output_tokens": 3}), \
             patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fake_body):
            resp = await adapter.complete(_req())
            assert isinstance(resp, LLMResponse)
            assert resp.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_complete_timeout(self):
        from app.backend.llm.bedrock_adapter import BedrockAdapter
        from app.backend.core.errors import GenerationTimeout
        adapter = BedrockAdapter.__new__(BedrockAdapter)
        adapter._client = MagicMock()
        adapter._region = "us-east-1"

        async def raise_timeout(*a, **kw):
            raise GenerationTimeout("timeout")

        with patch("asyncio.to_thread", side_effect=raise_timeout):
            with pytest.raises(GenerationTimeout):
                await adapter.complete(_req())

    @pytest.mark.asyncio
    async def test_complete_upstream_error(self):
        from app.backend.llm.bedrock_adapter import BedrockAdapter
        from app.backend.core.errors import UpstreamError
        adapter = BedrockAdapter.__new__(BedrockAdapter)
        adapter._client = MagicMock()
        adapter._region = "us-east-1"

        async def raise_upstream(*a, **kw):
            raise UpstreamError("fail")

        with patch("asyncio.to_thread", side_effect=raise_upstream):
            with pytest.raises(UpstreamError):
                await adapter.complete(_req())


# ── Gemini adapter ─────────────────────────────────────────────────────

class TestGeminiAdapter:
    def test_init_no_key_raises(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "")
        from app.backend.core.config import get_settings
        get_settings.cache_clear()
        from app.backend.llm.gemini_adapter import GeminiAdapter
        with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
            GeminiAdapter()
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_complete_success(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
        from app.backend.core.config import get_settings
        get_settings.cache_clear()

        from app.backend.llm.gemini_adapter import GeminiAdapter
        adapter = GeminiAdapter.__new__(GeminiAdapter)
        adapter._client = MagicMock()

        def fake_invoke(request):
            return ('{"score": 1.0}', {"input_tokens": 10, "output_tokens": 5})

        adapter._invoke = fake_invoke

        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=('{"score": 1.0}', {"input_tokens": 10, "output_tokens": 5})):
            resp = await adapter.complete(_req(model="gemini-3.1-pro"))
            assert resp.text == '{"score": 1.0}'
            assert resp.latency_ms >= 0

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_complete_timeout(self, monkeypatch):
        from app.backend.core.errors import GenerationTimeout
        from app.backend.llm.gemini_adapter import GeminiAdapter
        adapter = GeminiAdapter.__new__(GeminiAdapter)
        adapter._client = MagicMock()

        async def raise_timeout(*a, **kw):
            raise GenerationTimeout("timeout")

        with patch("asyncio.to_thread", side_effect=raise_timeout):
            with pytest.raises(GenerationTimeout):
                await adapter.complete(_req(model="gemini-3.1-pro"))


# ── Factory branches ───────────────────────────────────────────────────

class TestFactory:
    def test_get_adapter_bedrock(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "bedrock")
        from app.backend.core.config import get_settings
        from app.backend.llm.factory import get_adapter, reset_adapter_cache
        get_settings.cache_clear()
        reset_adapter_cache()
        with patch("app.backend.llm.bedrock_adapter.BedrockAdapter") as mock_cls:
            mock_cls.return_value = MagicMock()
            adapter = get_adapter()
            mock_cls.assert_called_once()
        reset_adapter_cache()
        get_settings.cache_clear()

    def test_get_adapter_gemini(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GOOGLE_API_KEY", "fake")
        from app.backend.core.config import get_settings
        from app.backend.llm.factory import get_adapter, reset_adapter_cache
        get_settings.cache_clear()
        reset_adapter_cache()
        with patch("app.backend.llm.gemini_adapter.GeminiAdapter") as mock_cls:
            mock_cls.return_value = MagicMock()
            adapter = get_adapter()
            mock_cls.assert_called_once()
        reset_adapter_cache()
        get_settings.cache_clear()

    def test_get_judge_adapter_gemini(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        monkeypatch.setenv("JUDGE_PROVIDER", "gemini")
        monkeypatch.setenv("GOOGLE_API_KEY", "fake")
        from app.backend.core.config import get_settings
        from app.backend.llm.factory import get_judge_adapter, reset_adapter_cache
        get_settings.cache_clear()
        reset_adapter_cache()
        with patch("app.backend.llm.gemini_adapter.GeminiAdapter") as mock_cls:
            mock_cls.return_value = MagicMock()
            adapter = get_judge_adapter()
            mock_cls.assert_called_once()
        reset_adapter_cache()
        get_settings.cache_clear()

    def test_get_judge_adapter_bedrock(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        monkeypatch.setenv("JUDGE_PROVIDER", "bedrock")
        from app.backend.core.config import get_settings
        from app.backend.llm.factory import get_judge_adapter, reset_adapter_cache
        get_settings.cache_clear()
        reset_adapter_cache()
        with patch("app.backend.llm.bedrock_adapter.BedrockAdapter") as mock_cls:
            mock_cls.return_value = MagicMock()
            adapter = get_judge_adapter()
            mock_cls.assert_called_once()
        reset_adapter_cache()
        get_settings.cache_clear()

    def test_get_judge_adapter_falls_back(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        monkeypatch.setenv("JUDGE_PROVIDER", "")
        from app.backend.core.config import get_settings
        from app.backend.llm.factory import get_adapter, get_judge_adapter, reset_adapter_cache
        get_settings.cache_clear()
        reset_adapter_cache()
        main = get_adapter()
        judge = get_judge_adapter()
        assert main is judge
        reset_adapter_cache()
        get_settings.cache_clear()
