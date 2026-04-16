"""Scenario / reference loading for the evaluation harness.

Scenarios and reference emails live as JSON files under `eval/scenarios` and
`eval/references`. The runner loads a named set (default `default_10`) and
pairs each scenario with its reference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.backend.core.config import get_settings
from app.backend.core.errors import NotFound


@dataclass(slots=True)
class Scenario:
    scenario_id: str
    title: str
    intent: str
    key_facts: list[str]
    tone: str
    difficulty: str = "medium"


@dataclass(slots=True)
class Reference:
    scenario_id: str
    reference_subject: str
    reference_email: str


@dataclass(slots=True)
class ScenarioSet:
    set_id: str
    scenarios: list[Scenario]
    references: dict[str, Reference]


def load_scenarios(set_id: str = "default_10") -> ScenarioSet:
    settings = get_settings()
    scenarios_path = Path(settings.eval_scenarios_dir) / f"{set_id}.json"
    references_path = Path(settings.eval_references_dir) / f"{set_id}.json"

    if not scenarios_path.exists():
        raise NotFound(f"scenario set not found: {scenarios_path}")
    if not references_path.exists():
        raise NotFound(f"reference set not found: {references_path}")

    with scenarios_path.open() as f:
        scenario_payload = json.load(f)
    with references_path.open() as f:
        reference_payload = json.load(f)

    scenarios = [
        Scenario(
            scenario_id=s["scenario_id"],
            title=s["title"],
            intent=s["intent"],
            key_facts=list(s["key_facts"]),
            tone=s["tone"],
            difficulty=s.get("difficulty", "medium"),
        )
        for s in scenario_payload["scenarios"]
    ]
    references = {
        r["scenario_id"]: Reference(
            scenario_id=r["scenario_id"],
            reference_subject=r.get("reference_subject", ""),
            reference_email=r["reference_email"],
        )
        for r in reference_payload["references"]
    }
    missing = [s.scenario_id for s in scenarios if s.scenario_id not in references]
    if missing:
        raise NotFound(f"missing references for scenarios: {missing}")

    return ScenarioSet(set_id=set_id, scenarios=scenarios, references=references)
