"""Tests for the scenario/reference loader."""

from __future__ import annotations

import pytest

from app.backend.core.errors import NotFound
from app.backend.evaluation.scenarios import load_scenarios


def test_loads_default_10_pairs_references():
    dataset = load_scenarios("default_10")
    assert len(dataset.scenarios) == 10
    ids = {s.scenario_id for s in dataset.scenarios}
    assert ids == set(dataset.references.keys())
    assert {"easy", "medium", "hard"} & {s.difficulty for s in dataset.scenarios}


def test_unknown_set_raises_not_found():
    with pytest.raises(NotFound):
        load_scenarios("does_not_exist")


def test_every_reference_is_non_empty():
    dataset = load_scenarios("default_10")
    for ref in dataset.references.values():
        assert len(ref.reference_email.strip()) > 80  # not a stub
