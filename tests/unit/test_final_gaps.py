"""Final targeted tests to push coverage over 90%."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.backend.main import app


# ── routes_health: readyz checks (lines 41-44, 50-51) ──────────────────

@pytest.mark.asyncio
async def test_readyz_checks_include_database():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/readyz")
        body = res.json()
        assert "checks" in body
        assert "database" in body["checks"]
        assert body["checks"]["database"] == "ok"
        assert "provider" in body["checks"]


@pytest.mark.asyncio
async def test_metrics_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/metrics")
        assert res.status_code == 200
        assert "http_requests_total" in res.text or "HELP" in res.text


# ── middleware: body size with valid large content-length (line 83-84) ──

@pytest.mark.asyncio
async def test_body_size_limit_rejects_large_post():
    """POST with Content-Length exceeding limit returns 413."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/generate",
            content="x" * 50_000,
            headers={"Content-Type": "application/json", "Content-Length": "50000"},
        )
        assert res.status_code == 413


@pytest.mark.asyncio
async def test_body_size_limit_allows_normal_post():
    """Normal-sized POST passes through body size middleware."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/generate",
            json={"intent": "test", "key_facts": ["f"], "tone": "formal"},
        )
        assert res.status_code == 200


# ── database: dispose_db (lines 56-59) ─────────────────────────────────

@pytest.mark.asyncio
async def test_dispose_db():
    from app.backend.persistence.database import dispose_db, get_engine
    # Ensure engine exists
    get_engine()
    await dispose_db()
    # After dispose, engine should be None
    from app.backend.persistence import database
    assert database._engine is None
    assert database._session_factory is None
    # Re-init for other tests
    from app.backend.persistence.database import init_db
    await init_db()


# ── scenarios: edge cases (lines 50, 78) ───────────────────────────────

def test_load_scenarios_default():
    from app.backend.evaluation.scenarios import load_scenarios
    dataset = load_scenarios("default_10")
    assert len(dataset.scenarios) == 10
    assert dataset.set_id == "default_10"


def test_load_scenarios_invalid_raises():
    from app.backend.evaluation.scenarios import load_scenarios
    from app.backend.core.errors import NotFound
    with pytest.raises(NotFound):
        load_scenarios("nonexistent_set_999")


# ── registry: unknown prompt raises (line 40) ──────────────────────────

def test_unknown_prompt_version_raises():
    from app.backend.prompts.registry import load_prompt
    from app.backend.core.errors import NotFound
    with pytest.raises(NotFound):
        load_prompt("totally_fake_v99")


# ── gemini adapter: complete with generic exception (lines 78-79) ──────

@pytest.mark.asyncio
async def test_gemini_complete_generic_exception():
    from unittest.mock import AsyncMock, patch
    from app.backend.llm.gemini_adapter import GeminiAdapter
    from app.backend.llm.base import LLMRequest, LLMMessage
    from app.backend.core.errors import UpstreamError

    adapter = GeminiAdapter.__new__(GeminiAdapter)
    adapter._client = None

    async def explode(*a, **kw):
        raise ValueError("something unexpected")

    with patch("asyncio.to_thread", side_effect=explode):
        with pytest.raises(UpstreamError, match="something unexpected"):
            await adapter.complete(LLMRequest(
                model="gemini-3.1-pro",
                system="sys",
                messages=[LLMMessage(role="user", content="hi")],
            ))
