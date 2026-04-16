"""ASGI middleware: request-id correlation, access logging, body-size limit,
security headers.

Order rules (see app/backend/main.py):
- `RequestContextMiddleware`  — binds `request_id` into structlog contextvars
- `PrometheusMiddleware`      — request/latency counters
- `BodySizeLimitMiddleware`   — reject oversized bodies before deserialization
- `SecurityHeadersMiddleware` — sets baseline response headers
- `CORSMiddleware`            — CORS allow-list
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.backend.core.logging import get_logger

log = get_logger("http")

_REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or f"req_{uuid.uuid4().hex[:16]}"
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Unhandled errors are logged by the global handler.
            latency_ms = int((time.perf_counter() - start) * 1000)
            log.error("request.error", method=request.method, latency_ms=latency_ms)
            raise
        latency_ms = int((time.perf_counter() - start) * 1000)
        response.headers[_REQUEST_ID_HEADER] = request_id
        log.info(
            "request.completed",
            method=request.method,
            status=response.status_code,
            latency_ms=latency_ms,
        )
        structlog.contextvars.clear_contextvars()
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds `max_bytes`.

    Defends against oversized-input abuse before we hand bytes to the body
    parser (docs/08 §4 "Input controls — max length checks"). Chunked
    requests without Content-Length are not rejected here — those are rare
    for our JSON endpoints and a deeper guard would require streaming.
    """

    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self._max = max_bytes

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method in {"POST", "PUT", "PATCH"}:
            length = request.headers.get("content-length")
            if length is not None:
                try:
                    n = int(length)
                except ValueError:
                    n = 0
                if n > self._max:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "PAYLOAD_TOO_LARGE",
                                "message": f"Request body exceeds {self._max} bytes.",
                                "request_id": getattr(request.state, "request_id", None),
                            }
                        },
                    )
        return await call_next(request)


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    # Strict CSP for the SPA surface. Model output is rendered strictly as
    # text via `textContent`, so we never need inline scripts.
    # Google Fonts is whitelisted for the Inter typeface.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set baseline security headers on every response.

    Docs/08_SECURITY_PRIVACY.md §4 "Output controls". The CSP is tight
    because the SPA has no inline scripts/styles and no third-party CDN.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response
