"""Repository layer — encapsulates all DB access behind small async functions.

Keeps service code free of SQLAlchemy specifics and makes mocking trivial.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.backend.persistence.models import Draft, DraftKeyFact, DraftRevision, EvalRun


class DraftRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        draft_id: str,
        intent: str,
        tone: str,
        key_facts: list[str],
        subject_suggestion: str | None,
        email_body: str,
        prompt_version: str,
        model_id: str,
    ) -> Draft:
        draft = Draft(
            id=draft_id,
            intent=intent,
            tone=tone,
            subject_suggestion=subject_suggestion,
            email_body=email_body,
            prompt_version=prompt_version,
            model_id=model_id,
            facts=[
                DraftKeyFact(fact_text=fact, sort_order=i) for i, fact in enumerate(key_facts)
            ],
        )
        self.session.add(draft)
        await self.session.commit()
        await self.session.refresh(draft)
        return draft

    async def get(self, draft_id: str) -> Draft | None:
        stmt = (
            select(Draft)
            .where(Draft.id == draft_id)
            .options(selectinload(Draft.facts), selectinload(Draft.revisions))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_revision(
        self,
        *,
        revision_id: str,
        draft_id: str,
        revision_instruction: str | None,
        prompt_version: str,
        model_id: str,
        subject_suggestion: str | None,
        email_body: str,
    ) -> DraftRevision:
        revision = DraftRevision(
            id=revision_id,
            draft_id=draft_id,
            revision_instruction=revision_instruction,
            prompt_version=prompt_version,
            model_id=model_id,
            subject_suggestion=subject_suggestion,
            email_body=email_body,
        )
        self.session.add(revision)
        await self.session.commit()
        await self.session.refresh(revision)
        return revision

    async def list_revisions(self, draft_id: str) -> list[DraftRevision]:
        stmt = (
            select(DraftRevision)
            .where(DraftRevision.draft_id == draft_id)
            .order_by(DraftRevision.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete(self, draft_id: str) -> bool:
        """Delete a draft (cascades to facts and revisions). Returns True if
        a row was removed, False if no draft existed."""
        stmt = delete(Draft).where(Draft.id == draft_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def delete_older_than(self, cutoff) -> int:
        """Delete drafts created before `cutoff` (a timezone-aware datetime).

        Used by the retention cleanup command. Returns number of rows removed.
        """
        stmt = delete(Draft).where(Draft.created_at < cutoff)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return int(result.rowcount or 0)


class EvalRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        run_id: str,
        run_name: str,
        scenario_set_id: str,
        config_a: dict[str, Any],
        config_b: dict[str, Any],
    ) -> EvalRun:
        run = EvalRun(
            id=run_id,
            run_name=run_name,
            scenario_set_id=scenario_set_id,
            config_a_json=json.dumps(config_a),
            config_b_json=json.dumps(config_b),
            status="queued",
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def get(self, run_id: str) -> EvalRun | None:
        stmt = select(EvalRun).where(EvalRun.id == run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def update_status(
        self,
        run_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        failure_reason: str | None = None,
    ) -> None:
        run = await self.get(run_id)
        if run is None:
            return
        run.status = status
        if result is not None:
            run.result_json = json.dumps(result, default=str)
        if failure_reason is not None:
            run.failure_reason = failure_reason
        run.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
