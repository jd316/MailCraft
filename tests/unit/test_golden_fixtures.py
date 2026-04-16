"""Golden fixture tests — docs/07_TEST_PLAN.md §4.

Each JSON file in tests/fixtures/golden/ defines a scenario + a frozen
generated email + expected deterministic metric values (with tolerance).
These tests keep the rule-based fact matcher and the structural quality
component stable across refactors.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.backend.evaluation.fact_matching import fact_inclusion_score
from app.backend.evaluation.metrics import _structural_quality

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "golden"


def _fixture_files() -> list[Path]:
    return sorted(p for p in FIXTURES.glob("*.json") if p.name != "README.md")


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.stem)
def test_golden(path: Path):
    data = json.loads(path.read_text())
    facts = data["scenario"]["key_facts"]
    email_body = data["email"]["body"]
    expected = data["expected"]

    fact_score, per_fact = fact_inclusion_score(facts, email_body)

    # Allow an exact match OR a min/max band.
    if "fact_inclusion" in expected:
        assert fact_score == pytest.approx(expected["fact_inclusion"], abs=1e-3), (
            path.name,
            fact_score,
        )
    else:
        lo = expected.get("fact_inclusion_min", 0.0)
        hi = expected.get("fact_inclusion_max", 1.0)
        assert lo <= fact_score <= hi, (path.name, fact_score, lo, hi)

    if "missing_indices" in expected:
        actually_missing = [i for i, p in enumerate(per_fact) if not p["included"]]
        assert actually_missing == expected["missing_indices"], (
            path.name,
            actually_missing,
        )

    struct_score, _ = _structural_quality(email_body)
    if "structural_professional_quality" in expected:
        assert struct_score == pytest.approx(
            expected["structural_professional_quality"], abs=1e-3
        )
    elif "structural_professional_quality_min" in expected:
        assert struct_score >= expected["structural_professional_quality_min"]


def test_fixtures_directory_is_populated():
    files = _fixture_files()
    assert len(files) >= 2, f"expected at least 2 golden fixtures, found {files}"
