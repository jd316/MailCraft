"""Export evaluation results as CSV and JSON."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_reports(*, out_dir: Path, run_id: str, payload: dict) -> dict[str, str]:
    """Write CSV + JSON reports and return a dict of artifact paths."""
    ensure_dir(out_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"{run_id}_{stamp}.csv"
    json_path = out_dir / f"{run_id}_{stamp}.json"

    # JSON: the full structured result.
    with json_path.open("w") as f:
        json.dump(payload, f, indent=2, default=str)

    # CSV: per-scenario, per-config scores — matches docs/06 §11 schema.
    columns = [
        "scenario_id",
        "config_label",
        "config_model",
        "config_prompt_version",
        "fact_inclusion",
        "tone_alignment",
        "professional_quality",
        "weighted_total",
    ]
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in payload.get("per_scenario", []):
            for label in ("config_a", "config_b"):
                cfg = payload["configs"][label]
                scores = row["scores"][label]
                writer.writerow(
                    [
                        row["scenario_id"],
                        label,
                        cfg["model_id"],
                        cfg["prompt_version"],
                        scores["fact_inclusion"],
                        scores["tone_alignment"],
                        scores["professional_quality"],
                        scores["weighted_total"],
                    ]
                )

    return {"csv": str(csv_path), "json": str(json_path)}
