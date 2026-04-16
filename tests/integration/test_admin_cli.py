"""Tests for the admin CLI (retention cleanup)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.backend.admin.cli import clean_drafts, main
from app.backend.main import app
from app.backend.persistence.database import get_session_factory
from app.backend.persistence.models import Draft


def test_clean_drafts_no_retention_is_noop(capsys):
    rc = main(["clean-drafts", "--days", "0"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deleted"] == 0


@pytest.mark.asyncio
async def test_clean_drafts_removes_old_rows():
    # Create a draft via the API, back-date it, then run the async cleanup.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/generate",
            json={
                "intent": "Follow up",
                "key_facts": ["Pilot begins May 12"],
                "tone": "formal",
            },
        )
        draft_id = res.json()["draft_id"]

    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            update(Draft)
            .where(Draft.id == draft_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=10))
        )
        await session.execute(stmt)
        await session.commit()

    dry = await clean_drafts(days=7, dry_run=True)
    assert dry["dry_run"] is True
    assert dry["would_delete"] >= 1

    real = await clean_drafts(days=7, dry_run=False)
    assert real["deleted"] >= 1

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        miss = await client.get(f"/v1/drafts/{draft_id}")
        assert miss.status_code == 404
