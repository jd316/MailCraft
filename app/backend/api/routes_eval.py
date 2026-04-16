"""Evaluation endpoints — start a run, fetch results."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Request

from app.backend.api.deps import eval_repo_dep
from app.backend.api.rate_limit import limiter
from app.backend.core.config import get_settings
from app.backend.core.errors import NotFound
from app.backend.core.schemas import (
    EvalAveragesByConfig,
    EvalConfig,
    EvalRunRequest,
    EvalRunResponse,
    EvalRunResult,
)
from app.backend.core.telemetry import EVAL_RUNS
from app.backend.evaluation.runner import EvaluationRunner
from app.backend.persistence.database import get_session_factory
from app.backend.persistence.repositories import EvalRunRepository

router = APIRouter(prefix="/v1", tags=["evaluation"])


def _eval_rate() -> str:
    return get_settings().rate_limit_eval


@router.post(
    "/evaluations/run",
    response_model=EvalRunResponse,
    summary="Start a comparative evaluation run",
    description=(
        "Kicks off a background evaluation of two configurations (model or "
        "prompt strategy) against the configured scenario set. Poll "
        "`GET /v1/evaluations/{id}` for status and the winner recommendation."
    ),
)
@limiter.limit(_eval_rate)
async def start_eval(
    request: Request,
    payload: EvalRunRequest,
    runs: EvalRunRepository = Depends(eval_repo_dep),
) -> EvalRunResponse:
    run_id = f"eval_{uuid.uuid4().hex[:12]}"
    await runs.create(
        run_id=run_id,
        run_name=payload.run_name,
        scenario_set_id=payload.scenario_set_id,
        config_a=payload.config_a.model_dump(),
        config_b=payload.config_b.model_dump(),
    )

    # Fire-and-forget in the running event loop. The task reads the shared
    # state via its own DB session so it survives after this response returns.
    asyncio.create_task(_run_eval_job(run_id, payload))
    return EvalRunResponse(evaluation_run_id=run_id, status="queued")


async def _run_eval_job(run_id: str, payload: EvalRunRequest) -> None:
    factory = get_session_factory()
    async with factory() as session:
        repo = EvalRunRepository(session)
        runner = EvaluationRunner()
        try:
            await repo.update_status(run_id, status="running")
            result = await runner.run(
                run_id=run_id,
                run_name=payload.run_name,
                config_a=payload.config_a,
                config_b=payload.config_b,
                scenario_set_id=payload.scenario_set_id,
            )
            await repo.update_status(run_id, status="completed", result=result)
            EVAL_RUNS.labels(status="completed").inc()
        except Exception as exc:  # noqa: BLE001 - surface any failure to caller
            await repo.update_status(run_id, status="failed", failure_reason=str(exc))
            EVAL_RUNS.labels(status="failed").inc()


@router.get(
    "/evaluations/{evaluation_run_id}",
    response_model=EvalRunResult,
    summary="Fetch evaluation status + averages + artifact paths",
    responses={404: {"description": "Evaluation run not found"}},
)
async def get_eval(
    evaluation_run_id: str,
    runs: EvalRunRepository = Depends(eval_repo_dep),
) -> EvalRunResult:
    run = await runs.get(evaluation_run_id)
    if run is None:
        raise NotFound(f"evaluation run {evaluation_run_id} not found")

    import json as _json

    result_payload = _json.loads(run.result_json) if run.result_json else None
    averages = None
    artifact_paths = None
    winner = None
    if result_payload:
        averages = {
            label: EvalAveragesByConfig(**scores)
            for label, scores in result_payload.get("average_scores", {}).items()
        }
        artifact_paths = result_payload.get("artifact_paths")
        winner = result_payload.get("recommended_winner")

    return EvalRunResult(
        evaluation_run_id=run.id,
        run_name=run.run_name,
        status=run.status,  # type: ignore[arg-type]
        config_a=EvalConfig(**_json.loads(run.config_a_json)),
        config_b=EvalConfig(**_json.loads(run.config_b_json)),
        average_scores=averages,
        artifact_paths=artifact_paths,
        recommended_winner=winner,
        failure_reason=run.failure_reason,
    )
