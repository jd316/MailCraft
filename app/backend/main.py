"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.backend.api.rate_limit import limiter, rate_limit_handler
from app.backend.api.routes_eval import router as eval_router
from app.backend.api.routes_generate import router as generate_router
from app.backend.api.routes_health import router as health_router
from app.backend.core.config import ROOT_DIR, get_settings
from app.backend.core.errors import (
    AppError,
    app_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.backend.core.logging import configure_logging, get_logger
from app.backend.core.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.backend.core.telemetry import PrometheusMiddleware
from app.backend.persistence.database import dispose_db, init_db

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    settings.validate_for_runtime()
    await init_db()
    log.info(
        "startup",
        app_env=settings.app_env,
        provider=settings.effective_provider,
        model_primary=settings.model_primary,
        model_fallback=settings.model_fallback,
    )
    yield
    await dispose_db()
    log.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="MailCraft API",
        version="1.0.0",
        description=(
            "MailCraft — Turn intent into inbox-ready emails, powered by LLM. "
            "Generates professional emails from (intent, key_facts, tone) using "
            "advanced prompting. Includes a comparison-ready evaluation harness."
        ),
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    # Middleware order matters — last added runs first. We want:
    # RequestContext (bind request_id) → Prometheus (latency ticking) →
    # BodySizeLimit (reject oversize early) → SecurityHeaders (set on response) → CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        allow_credentials=False,
        max_age=600,
    )
    if settings.enable_security_headers:
        app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(RequestContextMiddleware)

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(health_router)
    app.include_router(generate_router)
    app.include_router(eval_router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    frontend_dir = ROOT_DIR / "app" / "frontend"
    if not frontend_dir.exists():
        return

    # Mount static assets under /app, keep "/" for the SPA shell.
    assets_dir = frontend_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    favicon_path = assets_dir / "favicon.svg"
    if favicon_path.exists():
        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon() -> FileResponse:
            return FileResponse(str(favicon_path), media_type="image/svg+xml")

    index_path = frontend_dir / "index.html"
    if index_path.exists():
        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(str(index_path))


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    s = get_settings()
    uvicorn.run("app.backend.main:app", host=s.app_host, port=s.app_port, reload=False)
