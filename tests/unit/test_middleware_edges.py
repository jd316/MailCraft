"""Tests for middleware edge cases — malformed content-length, telemetry."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.backend.main import app


@pytest.mark.asyncio
async def test_malformed_content_length_handled():
    """Malformed Content-Length should not crash the body-size middleware."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/healthz", headers={"Content-Length": "abc"})
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_oversized_body_rejected():
    """Body exceeding MAX_BODY_BYTES should be rejected."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        huge = "x" * 100_000
        res = await client.post(
            "/v1/generate",
            content=huge,
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code in (413, 422, 400)


class TestTelemetry:
    def test_observe_llm_usage_with_cache(self):
        from app.backend.core.telemetry import observe_llm_usage
        usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 10,
        }
        observe_llm_usage(model="test-model", usage=usage)

    def test_observe_llm_usage_minimal(self):
        from app.backend.core.telemetry import observe_llm_usage
        observe_llm_usage(model="test-model", usage={"input_tokens": 10, "output_tokens": 5})

    def test_observe_llm_usage_empty(self):
        from app.backend.core.telemetry import observe_llm_usage
        observe_llm_usage(model="test-model", usage={})
