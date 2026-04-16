"""End-to-end API tests against the FastAPI app via httpx AsyncClient."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.backend.main import app


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/healthz")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_meta_exposes_provider_and_versions():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/v1/meta")
        assert res.status_code == 200
        data = res.json()
        assert data["provider"] == "mock"  # isolated via conftest
        assert "advanced_v1" in data["prompt_versions"]


@pytest.mark.asyncio
async def test_generate_flow_persists_draft_and_verifies_coverage():
    payload = {
        "intent": "Follow up after client review meeting",
        "key_facts": [
            "Pilot starts the week of May 12",
            "Revised pricing sheet by Friday",
            "Case studies on Thursday",
        ],
        "tone": "formal",
        "prompt_version": "advanced_v1",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/v1/generate", json=payload)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["subject_suggestion"]
        assert body["email_body"]
        assert body["draft_id"].startswith("draft_")
        assert body["prompt_version"] == "advanced_v1"
        assert len(body["fact_coverage"]) == len(payload["key_facts"])

        # Fetch it back.
        get_res = await client.get(f"/v1/drafts/{body['draft_id']}")
        assert get_res.status_code == 200
        got = get_res.json()
        assert got["intent"] == payload["intent"]
        assert got["key_facts"] == payload["key_facts"]


@pytest.mark.asyncio
async def test_missing_facts_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/generate",
            json={"intent": "hello", "key_facts": [], "tone": "formal"},
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_regenerate_requires_existing_draft():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/regenerate",
            json={"draft_id": "draft_nope", "revision_instruction": "shorter"},
        )
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_regenerate_creates_revision():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        base = await client.post(
            "/v1/generate",
            json={
                "intent": "Thank the panel after my interview",
                "key_facts": ["Interview was on April 14", "Platform team"],
                "tone": "friendly",
            },
        )
        draft_id = base.json()["draft_id"]
        res = await client.post(
            "/v1/regenerate",
            json={"draft_id": draft_id, "revision_instruction": "Make it slightly warmer"},
        )
        assert res.status_code == 200
        assert res.json()["draft_id"] == draft_id

        detail = await client.get(f"/v1/drafts/{draft_id}")
        assert detail.json()["revisions"] >= 1
