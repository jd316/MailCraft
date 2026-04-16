"""Tests for the full draft lifecycle: create → revise → list revisions → delete."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.backend.main import app


@pytest.mark.asyncio
async def test_list_revisions_returns_full_history():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        base = await client.post(
            "/v1/generate",
            json={
                "intent": "Follow up",
                "key_facts": ["Pilot begins May 12"],
                "tone": "formal",
            },
        )
        draft_id = base.json()["draft_id"]

        # Two revisions.
        await client.post(
            "/v1/regenerate",
            json={"draft_id": draft_id, "revision_instruction": "shorter"},
        )
        await client.post(
            "/v1/regenerate",
            json={"draft_id": draft_id, "revision_instruction": "warmer"},
        )

        res = await client.get(f"/v1/drafts/{draft_id}/revisions")
        assert res.status_code == 200
        revisions = res.json()
        assert len(revisions) == 2
        assert [r["revision_instruction"] for r in revisions] == ["shorter", "warmer"]
        # All revisions reference the same parent draft.
        assert all(r["draft_id"] == draft_id for r in revisions)
        # Revision ids are distinct.
        assert len({r["revision_id"] for r in revisions}) == 2


@pytest.mark.asyncio
async def test_list_revisions_404_on_missing_draft():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/v1/drafts/draft_nope/revisions")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_draft_cascades_to_revisions():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        base = await client.post(
            "/v1/generate",
            json={
                "intent": "Follow up",
                "key_facts": ["Pilot begins May 12"],
                "tone": "formal",
            },
        )
        draft_id = base.json()["draft_id"]
        await client.post(
            "/v1/regenerate",
            json={"draft_id": draft_id, "revision_instruction": "shorter"},
        )

        # Delete.
        res = await client.delete(f"/v1/drafts/{draft_id}")
        assert res.status_code == 200
        assert res.json() == {"draft_id": draft_id, "deleted": True}

        # Subsequent reads 404.
        assert (await client.get(f"/v1/drafts/{draft_id}")).status_code == 404
        assert (await client.get(f"/v1/drafts/{draft_id}/revisions")).status_code == 404


@pytest.mark.asyncio
async def test_delete_missing_draft_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.delete("/v1/drafts/draft_never_existed")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"
