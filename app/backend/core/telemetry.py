"""Prometheus instrumentation.

Exposes a small, intentional set of metrics. We do **not** auto-instrument
every handler — the labels would explode and most of them are redundant
with structured logs. Instead we expose the ones operators actually alert
on: request counters & latency by method+path+status, and upstream model
token usage.

Endpoint:     GET /metrics  (registered in main.py)
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

HTTP_REQUESTS = Counter(
    "ega_http_requests_total",
    "HTTP requests by method, path template, and status code.",
    ["method", "path", "status"],
)

HTTP_LATENCY = Histogram(
    "ega_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0),
)

LLM_TOKENS = Counter(
    "ega_llm_tokens_total",
    "LLM tokens consumed.",
    ["model", "direction"],  # direction: input|output|cache_read|cache_write
)

EVAL_RUNS = Counter(
    "ega_eval_runs_total",
    "Evaluation runs by terminal status.",
    ["status"],  # completed|failed
)


def observe_llm_usage(model: str, usage: dict) -> None:
    if not usage:
        return
    LLM_TOKENS.labels(model=model, direction="input").inc(usage.get("input_tokens", 0) or 0)
    LLM_TOKENS.labels(model=model, direction="output").inc(usage.get("output_tokens", 0) or 0)
    LLM_TOKENS.labels(model=model, direction="cache_read").inc(
        usage.get("cache_read_input_tokens", 0) or 0
    )
    LLM_TOKENS.labels(model=model, direction="cache_write").inc(
        usage.get("cache_creation_input_tokens", 0) or 0
    )


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Records request counts + latency against the matched route template.

    Using the route template (e.g. `/v1/drafts/{draft_id}`) instead of the
    raw path prevents label cardinality from blowing up with identifiers.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            path = _route_template(request) or request.url.path
            HTTP_REQUESTS.labels(
                method=request.method, path=path, status=str(status)
            ).inc()
            HTTP_LATENCY.labels(method=request.method, path=path).observe(
                time.perf_counter() - start
            )


def _route_template(request: Request) -> str | None:
    # Starlette populates `request.scope["route"]` after matching.
    route = request.scope.get("route")
    if route is None:
        return None
    path = getattr(route, "path", None)
    return path


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
