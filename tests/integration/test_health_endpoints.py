"""Tests for the health, readiness, metrics, and metadata endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.backend.main import app


@pytest.mark.asyncio
async def test_readyz_reports_db_and_provider_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/readyz")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["checks"]["database"] == "ok"
        assert data["checks"]["provider"] == "mock"


@pytest.mark.asyncio
async def test_metrics_exposes_prometheus_text():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First make a call so at least one metric gets populated.
        await client.get("/healthz")
        res = await client.get("/metrics")
        assert res.status_code == 200
        # Default Prometheus text exposition content type.
        assert "text/plain" in res.headers["content-type"]
        body = res.text
        assert "ega_http_requests_total" in body
        assert "ega_http_request_duration_seconds" in body


@pytest.mark.asyncio
async def test_security_headers_set():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/healthz")
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in res.headers


@pytest.mark.asyncio
async def test_request_id_header_echoed():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/healthz", headers={"X-Request-ID": "test-fixed-id"})
        assert res.headers["X-Request-ID"] == "test-fixed-id"
