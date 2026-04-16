"""Tests for the CSV/JSON report writer."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.backend.evaluation.reports import write_reports


def test_reports_roundtrip(tmp_path: Path):
    payload = {
        "run_id": "eval_rx",
        "run_name": "unit",
        "configs": {
            "config_a": {"model_id": "m", "prompt_version": "baseline_v1"},
            "config_b": {"model_id": "m", "prompt_version": "advanced_v1"},
        },
        "per_scenario": [
            {
                "scenario_id": "S01",
                "scores": {
                    "config_a": {
                        "fact_inclusion": 0.9,
                        "tone_alignment": 0.8,
                        "professional_quality": 0.85,
                        "weighted_total": 0.865,
                    },
                    "config_b": {
                        "fact_inclusion": 1.0,
                        "tone_alignment": 0.9,
                        "professional_quality": 0.9,
                        "weighted_total": 0.945,
                    },
                },
            }
        ],
    }
    paths = write_reports(out_dir=tmp_path, run_id="eval_rx", payload=payload)
    csv_path = Path(paths["csv"])
    json_path = Path(paths["json"])

    assert csv_path.exists() and json_path.exists()
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert {r["config_label"] for r in rows} == {"config_a", "config_b"}

    roundtrip = json.loads(json_path.read_text())
    assert roundtrip["run_id"] == "eval_rx"
