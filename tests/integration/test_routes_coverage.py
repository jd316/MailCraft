"""Integration tests to cover route branches — 404s, regenerate, drafts, delete."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.backend.main import app


@pytest.mark.asyncio
async def test_generate_returns_fact_coverage_items():
    """POST /v1/generate returns properly shaped fact_coverage."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/v1/generate", json={
            "intent": "Follow up",
            "key_facts": ["Budget approved"],
            "tone": "formal",
        })
        assert res.status_code == 200
        body = res.json()
        assert "fact_coverage" in body
        assert isinstance(body["fact_coverage"], list)
        assert all("fact" in fc and "included" in fc for fc in body["fact_coverage"])


@pytest.mark.asyncio
async def test_regenerate_nonexistent_draft_404():
    """POST /v1/regenerate with bad draft_id returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/v1/regenerate", json={
            "draft_id": "draft_does_not_exist",
            "revision_instruction": "make it shorter",
        })
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_draft_nonexistent_404():
    """GET /v1/drafts/{id} with bad id returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/v1/drafts/draft_does_not_exist")
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_revisions_nonexistent_404():
    """GET /v1/drafts/{id}/revisions with bad id returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/v1/drafts/draft_does_not_exist/revisions")
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_draft_nonexistent_404():
    """DELETE /v1/drafts/{id} with bad id returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.delete("/v1/drafts/draft_does_not_exist")
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_full_lifecycle_generate_then_regenerate():
    """Generate → regenerate → get draft → get revisions → delete."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Generate
        gen = await client.post("/v1/generate", json={
            "intent": "Test lifecycle",
            "key_facts": ["fact one"],
            "tone": "casual",
        })
        assert gen.status_code == 200
        draft_id = gen.json()["draft_id"]

        # Regenerate
        regen = await client.post("/v1/regenerate", json={
            "draft_id": draft_id,
            "revision_instruction": "make it shorter",
        })
        assert regen.status_code == 200
        assert regen.json()["draft_id"] == draft_id

        # Get draft
        draft = await client.get(f"/v1/drafts/{draft_id}")
        assert draft.status_code == 200

        # Get revisions
        revs = await client.get(f"/v1/drafts/{draft_id}/revisions")
        assert revs.status_code == 200
        assert isinstance(revs.json(), list)

        # Delete
        delete = await client.delete(f"/v1/drafts/{draft_id}")
        assert delete.status_code == 200

        # Verify deleted
        after = await client.get(f"/v1/drafts/{draft_id}")
        assert after.status_code == 404
