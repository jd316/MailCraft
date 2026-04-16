"""Rate-limit enforcement — 429 with the documented error envelope."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def rate_limited_app():
    """Build a fresh app with an extremely low generation rate so the test
    doesn't flap in CI or interact with other tests' counters."""
    os.environ["RATE_LIMIT_GENERATE"] = "2/minute"
    from app.backend.api.rate_limit import limiter
    from app.backend.core.config import get_settings

    get_settings.cache_clear()
    limiter.reset()

    from app.backend.main import create_app

    app = create_app()
    try:
        yield app
    finally:
        os.environ.pop("RATE_LIMIT_GENERATE", None)
        get_settings.cache_clear()
        limiter.reset()


@pytest.mark.asyncio
async def test_generate_rate_limit_returns_envelope(rate_limited_app):
    payload = {
        "intent": "Follow up",
        "key_facts": ["pilot begins May 12"],
        "tone": "formal",
    }
    async with AsyncClient(
        transport=ASGITransport(app=rate_limited_app), base_url="http://test"
    ) as client:
        # Init DB since lifespan doesn't run under ASGITransport.
        from app.backend.persistence.database import init_db

        await init_db()
        r1 = await client.post("/v1/generate", json=payload)
        r2 = await client.post("/v1/generate", json=payload)
        r3 = await client.post("/v1/generate", json=payload)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429
        assert r3.json()["error"]["code"] == "RATE_LIMITED"
