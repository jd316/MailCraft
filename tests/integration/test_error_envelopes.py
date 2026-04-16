"""Every failure path must return the documented error envelope.

Contract: `{ "error": { "code": str, "message": str, "request_id": str|null } }`
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.backend.main import app


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_validation_error_envelope():
    async with await _client() as client:
        res = await client.post(
            "/v1/generate",
            json={"intent": "x", "key_facts": [], "tone": "formal"},
        )
        assert res.status_code == 400
        env = res.json()["error"]
        assert env["code"] == "VALIDATION_ERROR"
        assert env["request_id"]
        assert "details" in env and env["details"]["errors"]


@pytest.mark.asyncio
async def test_not_found_envelope():
    async with await _client() as client:
        res = await client.get("/v1/drafts/draft_missing")
        assert res.status_code == 404
        env = res.json()["error"]
        assert env["code"] == "NOT_FOUND"
        assert env["request_id"]


@pytest.mark.asyncio
async def test_http_404_envelope_on_unknown_route():
    async with await _client() as client:
        res = await client.get("/no-such-route")
        assert res.status_code == 404
        env = res.json()["error"]
        assert env["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_payload_too_large_envelope():
    async with await _client() as client:
        res = await client.post(
            "/v1/generate",
            headers={"content-length": "999999"},
            content=b"{}",
        )
        # The middleware short-circuits before body parsing.
        assert res.status_code == 413
        env = res.json()["error"]
        assert env["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.asyncio
async def test_extra_fields_rejected_with_validation_envelope():
    async with await _client() as client:
        res = await client.post(
            "/v1/generate",
            json={
                "intent": "Follow up",
                "key_facts": ["Pilot starts May 12"],
                "tone": "formal",
                "evil_extra": 1,
            },
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"
