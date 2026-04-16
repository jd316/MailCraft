"""End-to-end CLI test for the evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path


def test_cli_run_writes_artifacts(tmp_path: Path, capsys):
    from app.backend.evaluation.cli import main

    exit_code = main(["run", "--out", str(tmp_path), "--name", "cli-test"])
    assert exit_code == 0
    captured = capsys.readouterr()
    # Logs go to stderr; JSON summary is the entire stdout.
    payload = json.loads(captured.out)
    assert payload["run_id"].startswith("eval_")
    assert payload["recommended_winner"] in {"config_a", "config_b", "tie"}
    # Files on disk.
    csv_files = list(tmp_path.glob("*.csv"))
    json_files = list(tmp_path.glob("*.json"))
    assert csv_files and json_files


def test_cli_rejects_both_compare_flags(capsys):
    from app.backend.evaluation.cli import main

    code = main(
        [
            "run",
            "--compare",
            "baseline_v1",
            "advanced_v1",
            "--compare-models",
            "m-a",
            "m-b",
        ]
    )
    assert code == 2
    assert "either --compare" in capsys.readouterr().err.lower()


def test_cli_compare_models_mode(tmp_path: Path):
    from app.backend.evaluation.cli import main

    exit_code = main(
        [
            "run",
            "--compare-models",
            "mock-haiku",
            "mock-sonnet",
            "--prompt",
            "advanced_v1",
            "--out",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
