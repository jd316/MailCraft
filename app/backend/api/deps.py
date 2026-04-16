"""FastAPI dependency wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.llm.base import LLMAdapter
from app.backend.llm.factory import get_adapter
from app.backend.persistence.database import get_session
from app.backend.persistence.repositories import DraftRepository, EvalRunRepository
from app.backend.services.generation import GenerationService


async def session_dep() -> AsyncIterator[AsyncSession]:
    async for s in get_session():
        yield s


def adapter_dep() -> LLMAdapter:
    return get_adapter()


def draft_repo_dep(session: AsyncSession = Depends(session_dep)) -> DraftRepository:
    return DraftRepository(session)


def eval_repo_dep(session: AsyncSession = Depends(session_dep)) -> EvalRunRepository:
    return EvalRunRepository(session)


def generation_service_dep(adapter: LLMAdapter = Depends(adapter_dep)) -> GenerationService:
    return GenerationService(adapter)
