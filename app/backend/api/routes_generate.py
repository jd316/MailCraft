"""/v1/generate + /v1/regenerate + /v1/drafts/{id}."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from app.backend.api.deps import draft_repo_dep, generation_service_dep
from app.backend.api.rate_limit import limiter
from app.backend.core.config import get_settings
from app.backend.core.errors import NotFound
from app.backend.core.schemas import (
    DraftDeletedResponse,
    DraftResponse,
    FactCoverageItem,
    GenerateRequest,
    GenerateResponse,
    RegenerateRequest,
    RevisionResponse,
)
from app.backend.persistence.repositories import DraftRepository
from app.backend.services.generation import GenerationService

router = APIRouter(prefix="/v1", tags=["generation"])


def _gen_rate() -> str:
    return get_settings().rate_limit_generate


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Generate an email draft",
    description=(
        "Turn a structured brief — intent, key facts, tone — into a polished "
        "email draft. The selected `prompt_version` (default `advanced_v1`) "
        "controls which prompt strategy is used. The response includes "
        "per-fact coverage so callers can highlight missing facts."
    ),
    responses={
        400: {"description": "Validation error (empty facts, bad tone, etc.)"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Upstream model failure"},
        504: {"description": "Model timeout"},
    },
)
@limiter.limit(_gen_rate)
async def generate(
    request: Request,
    payload: GenerateRequest,
    service: GenerationService = Depends(generation_service_dep),
    drafts: DraftRepository = Depends(draft_repo_dep),
) -> GenerateResponse:
    output = await service.generate(
        intent=payload.intent,
        key_facts=payload.key_facts,
        tone=payload.tone,
        prompt_version=payload.prompt_version,
        model_id=payload.model_id,
    )

    await drafts.create(
        draft_id=output.draft_id,
        intent=payload.intent,
        tone=payload.tone,
        key_facts=payload.key_facts,
        subject_suggestion=output.subject_suggestion,
        email_body=output.email_body,
        prompt_version=output.prompt_version,
        model_id=output.model_id,
    )

    return GenerateResponse(
        request_id=request.state.request_id,
        draft_id=output.draft_id,
        subject_suggestion=output.subject_suggestion,
        email_body=output.email_body,
        fact_coverage=[FactCoverageItem(**c) for c in output.fact_coverage],
        model_id=output.model_id,
        prompt_version=output.prompt_version,
        latency_ms=output.latency_ms,
    )


@router.post(
    "/regenerate",
    response_model=GenerateResponse,
    summary="Regenerate a draft with a revision instruction",
    responses={
        400: {"description": "Validation error"},
        404: {"description": "Draft not found"},
        429: {"description": "Rate limit exceeded"},
    },
)
@limiter.limit(_gen_rate)
async def regenerate(
    request: Request,
    payload: RegenerateRequest,
    service: GenerationService = Depends(generation_service_dep),
    drafts: DraftRepository = Depends(draft_repo_dep),
) -> GenerateResponse:
    draft = await drafts.get(payload.draft_id)
    if draft is None:
        raise NotFound(f"draft {payload.draft_id} not found")

    key_facts = [f.fact_text for f in draft.facts]
    output = await service.generate(
        intent=draft.intent,
        key_facts=key_facts,
        tone=draft.tone,
        prompt_version=payload.prompt_version or draft.prompt_version,
        model_id=payload.model_id or draft.model_id,
        revision_instruction=payload.revision_instruction,
        prior_draft=draft.email_body,
    )

    await drafts.add_revision(
        revision_id=f"rev_{uuid.uuid4().hex[:16]}",
        draft_id=draft.id,
        revision_instruction=payload.revision_instruction,
        prompt_version=output.prompt_version,
        model_id=output.model_id,
        subject_suggestion=output.subject_suggestion,
        email_body=output.email_body,
    )

    return GenerateResponse(
        request_id=request.state.request_id,
        draft_id=draft.id,
        subject_suggestion=output.subject_suggestion,
        email_body=output.email_body,
        fact_coverage=[FactCoverageItem(**c) for c in output.fact_coverage],
        model_id=output.model_id,
        prompt_version=output.prompt_version,
        latency_ms=output.latency_ms,
    )


@router.get(
    "/drafts/{draft_id}",
    response_model=DraftResponse,
    summary="Fetch a persisted draft by id",
    responses={404: {"description": "Draft not found"}},
)
async def get_draft(
    draft_id: str,
    drafts: DraftRepository = Depends(draft_repo_dep),
) -> DraftResponse:
    draft = await drafts.get(draft_id)
    if draft is None:
        raise NotFound(f"draft {draft_id} not found")
    return DraftResponse(
        draft_id=draft.id,
        intent=draft.intent,
        key_facts=[f.fact_text for f in draft.facts],
        tone=draft.tone,
        subject_suggestion=draft.subject_suggestion,
        email_body=draft.email_body,
        prompt_version=draft.prompt_version,
        model_id=draft.model_id,
        created_at=draft.created_at,
        revisions=len(draft.revisions),
    )


@router.get(
    "/drafts/{draft_id}/revisions",
    response_model=list[RevisionResponse],
    summary="List revisions for a draft (history of prior generations)",
    responses={404: {"description": "Draft not found"}},
)
async def list_revisions(
    draft_id: str,
    drafts: DraftRepository = Depends(draft_repo_dep),
) -> list[RevisionResponse]:
    draft = await drafts.get(draft_id)
    if draft is None:
        raise NotFound(f"draft {draft_id} not found")
    revisions = await drafts.list_revisions(draft_id)
    return [
        RevisionResponse(
            revision_id=r.id,
            draft_id=r.draft_id,
            revision_instruction=r.revision_instruction,
            prompt_version=r.prompt_version,
            model_id=r.model_id,
            subject_suggestion=r.subject_suggestion,
            email_body=r.email_body,
            created_at=r.created_at,
        )
        for r in revisions
    ]


@router.delete(
    "/drafts/{draft_id}",
    response_model=DraftDeletedResponse,
    summary="Delete a draft and its revisions",
    responses={404: {"description": "Draft not found"}},
)
async def delete_draft(
    draft_id: str,
    drafts: DraftRepository = Depends(draft_repo_dep),
) -> DraftDeletedResponse:
    ok = await drafts.delete(draft_id)
    if not ok:
        raise NotFound(f"draft {draft_id} not found")
    return DraftDeletedResponse(draft_id=draft_id, deleted=True)
