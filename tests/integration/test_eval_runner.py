"""Integration tests for the evaluation runner end-to-end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.backend.core.schemas import EvalConfig
from app.backend.evaluation.runner import EvaluationRunner


@pytest.mark.asyncio
async def test_runner_produces_valid_report_structure():
    runner = EvaluationRunner()
    config_a = EvalConfig(model_id="mock-a", prompt_version="baseline_v1", label="baseline")
    config_b = EvalConfig(model_id="mock-b", prompt_version="advanced_v1", label="advanced")

    payload = await runner.run(
        run_id="eval_test_run",
        run_name="runner-smoke",
        config_a=config_a,
        config_b=config_b,
    )

    # Per-scenario rows line up with the loaded set.
    assert len(payload["per_scenario"]) == 10

    for row in payload["per_scenario"]:
        for label in ("config_a", "config_b"):
            scores = row["scores"][label]
            for m in ("fact_inclusion", "tone_alignment", "professional_quality", "weighted_total"):
                assert 0.0 <= scores[m] <= 1.0, (row["scenario_id"], label, m, scores)

    averages = payload["average_scores"]
    for label in ("config_a", "config_b"):
        for m in ("fact_inclusion", "tone_alignment", "professional_quality", "weighted_total"):
            assert 0.0 <= averages[label][m] <= 1.0

    assert payload["recommended_winner"] in {"config_a", "config_b", "tie"}
    assert {"csv", "json"}.issubset(set(payload["artifact_paths"]))

    csv_path = Path(payload["artifact_paths"]["csv"])
    json_path = Path(payload["artifact_paths"]["json"])
    assert csv_path.exists() and csv_path.stat().st_size > 0
    assert json_path.exists() and json_path.stat().st_size > 0

    # CSV should have 20 data rows (10 scenarios × 2 configs) + 1 header.
    rows = csv_path.read_text().strip().splitlines()
    assert len(rows) == 21

    # JSON roundtrips.
    roundtrip = json.loads(json_path.read_text())
    assert roundtrip["run_id"] == "eval_test_run"
    assert "metric_definitions" in roundtrip


@pytest.mark.asyncio
async def test_mock_advanced_beats_baseline_on_fact_inclusion():
    """The mock adapter deliberately drops ~35% of baseline facts, so the
    advanced strategy should score strictly higher on fact inclusion. This
    makes the comparison meaningful even without an API key."""
    runner = EvaluationRunner()
    payload = await runner.run(
        run_id="eval_compare",
        run_name="baseline-vs-advanced",
        config_a=EvalConfig(model_id="mock-m", prompt_version="baseline_v1", label="baseline"),
        config_b=EvalConfig(model_id="mock-m", prompt_version="advanced_v1", label="advanced"),
    )
    a = payload["average_scores"]["config_a"]["fact_inclusion"]
    b = payload["average_scores"]["config_b"]["fact_inclusion"]
    assert b >= a  # advanced never worse
    assert payload["recommended_winner"] in {"config_b", "tie"}
