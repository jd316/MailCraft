"""Health, readiness, and metadata endpoints.

Split per k8s convention:
- `/healthz` — liveness: process is up. Should never fail due to dep state.
- `/readyz`  — readiness: we can serve real traffic (DB reachable, provider
  configured). Orchestrators should route traffic only when this is 200.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.backend.core.config import get_settings
from app.backend.core.logging import get_logger
from app.backend.core.telemetry import metrics_response
from app.backend.persistence.database import get_session_factory
from app.backend.prompts.registry import list_versions

log = get_logger("health")

router = APIRouter(tags=["meta"])


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe")
async def readyz(response: Response) -> dict:
    checks: dict[str, str] = {}
    ok = True

    # DB check
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        ok = False
        checks["database"] = f"error: {exc}"
        log.warning("readyz.db_failed", error=str(exc))

    # Provider configuration
    s = get_settings()
    checks["provider"] = s.effective_provider
    if s.app_env == "production" and s.effective_provider == "mock":
        ok = False
        checks["provider_warning"] = "mock provider in production"

    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "degraded", "checks": checks}


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics() -> Response:
    return metrics_response()


@router.get("/v1/meta", summary="App metadata")
async def meta() -> dict:
    s = get_settings()
    return {
        "app_env": s.app_env,
        "provider": s.effective_provider,
        "model_primary": s.model_primary,
        "model_secondary": s.model_secondary,
        "model_fallback": s.model_fallback,
        "prompt_versions": list_versions(),
        "version": "1.0.0",
    }
