"""End-to-end test for the evaluation API (POST run → GET status)."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.backend.main import app


@pytest.mark.asyncio
async def test_eval_api_run_and_fetch():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "run_name": "api-test-run",
            "config_a": {
                "model_id": "claude-sonnet-4-6",
                "prompt_version": "baseline_v1",
                "label": "baseline",
            },
            "config_b": {
                "model_id": "claude-sonnet-4-6",
                "prompt_version": "advanced_v1",
                "label": "advanced",
            },
            "scenario_set_id": "default_10",
        }
        res = await client.post("/v1/evaluations/run", json=payload)
        assert res.status_code == 200, res.text
        run_id = res.json()["evaluation_run_id"]
        assert res.json()["status"] in {"queued", "running", "completed"}

        # Background task runs in the event loop — wait for completion.
        for _ in range(40):
            detail = await client.get(f"/v1/evaluations/{run_id}")
            assert detail.status_code == 200
            status = detail.json()["status"]
            if status in {"completed", "failed"}:
                break
            await asyncio.sleep(0.05)

        final = await client.get(f"/v1/evaluations/{run_id}")
        body = final.json()
        assert body["status"] == "completed", body
        assert body["average_scores"] is not None
        assert body["recommended_winner"] in {"config_a", "config_b", "tie"}
        assert body["artifact_paths"]["csv"].endswith(".csv")
        assert body["artifact_paths"]["json"].endswith(".json")


@pytest.mark.asyncio
async def test_eval_api_unknown_run_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/v1/evaluations/eval_does_not_exist")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"
