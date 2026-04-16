"""Tests targeting remaining coverage gaps — health routes, logging, database, gemini invoke."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.backend.main import app


# ── Health routes (lines 41-44, 50-51) ─────────────────────────────────

@pytest.mark.asyncio
async def test_readyz_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/readyz")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_meta_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/v1/meta")
        assert res.status_code == 200
        body = res.json()
        assert "provider" in body
        assert "model_primary" in body


# ── Logging (line 23 — redaction, line 54 — structlog config) ──────────

def test_sensitive_key_redacted():
    from app.backend.core.logging import _redact
    event_dict = {"api_key": "secret123", "name": "visible"}
    result = _redact(None, None, event_dict)
    assert result["api_key"] == "***REDACTED***"
    assert result["name"] == "visible"


def test_configure_logging_idempotent():
    from app.backend.core.logging import configure_logging
    configure_logging()
    configure_logging()  # should not raise


# ── Gemini adapter _invoke ─────────────────────────────────────────────

class TestGeminiInvoke:
    def test_invoke_success(self):
        from app.backend.llm.gemini_adapter import GeminiAdapter
        from app.backend.llm.base import LLMRequest, LLMMessage

        adapter = GeminiAdapter.__new__(GeminiAdapter)

        fake_usage = MagicMock()
        fake_usage.prompt_token_count = 10
        fake_usage.candidates_token_count = 5

        fake_response = MagicMock()
        fake_response.text = '{"score": 1.0}'
        fake_response.usage_metadata = fake_usage

        fake_models = MagicMock()
        fake_models.generate_content.return_value = fake_response

        fake_client = MagicMock()
        fake_client.models = fake_models
        adapter._client = fake_client

        request = LLMRequest(
            model="gemini-3.1-pro",
            system="sys prompt",
            messages=[LLMMessage(role="user", content="hello")],
            temperature=0.0,
            max_tokens=400,
            response_format="json",
        )

        text, usage = adapter._invoke(request)
        assert text == '{"score": 1.0}'
        assert usage["input_tokens"] == 10
        assert usage["output_tokens"] == 5

    def test_invoke_timeout_raises(self):
        from app.backend.llm.gemini_adapter import GeminiAdapter
        from app.backend.llm.base import LLMRequest, LLMMessage
        from app.backend.core.errors import GenerationTimeout

        adapter = GeminiAdapter.__new__(GeminiAdapter)
        fake_client = MagicMock()
        fake_client.models.generate_content.side_effect = Exception("deadline exceeded")
        adapter._client = fake_client

        request = LLMRequest(
            model="gemini-3.1-pro",
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )

        with pytest.raises(GenerationTimeout):
            adapter._invoke(request)

    def test_invoke_generic_error_raises(self):
        from app.backend.llm.gemini_adapter import GeminiAdapter
        from app.backend.llm.base import LLMRequest, LLMMessage
        from app.backend.core.errors import UpstreamError

        adapter = GeminiAdapter.__new__(GeminiAdapter)
        fake_client = MagicMock()
        fake_client.models.generate_content.side_effect = Exception("something broke")
        adapter._client = fake_client

        request = LLMRequest(
            model="gemini-3.1-pro",
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )

        with pytest.raises(UpstreamError):
            adapter._invoke(request)

    def test_invoke_none_text(self):
        from app.backend.llm.gemini_adapter import GeminiAdapter
        from app.backend.llm.base import LLMRequest, LLMMessage

        adapter = GeminiAdapter.__new__(GeminiAdapter)
        fake_usage = MagicMock()
        fake_usage.prompt_token_count = 0
        fake_usage.candidates_token_count = 0

        fake_response = MagicMock()
        fake_response.text = None
        fake_response.usage_metadata = fake_usage

        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = fake_response
        adapter._client = fake_client

        request = LLMRequest(
            model="gemini-3.1-pro",
            system="sys",
            messages=[LLMMessage(role="user", content="hi")],
        )

        text, usage = adapter._invoke(request)
        assert text == ""
