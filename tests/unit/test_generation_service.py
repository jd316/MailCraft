"""Tests for the generation service parsing and fact-verification logic."""

from __future__ import annotations

import pytest

from app.backend.llm.mock_adapter import MockAdapter
from app.backend.services.generation import GenerationService


@pytest.mark.asyncio
async def test_service_returns_fact_coverage_per_fact():
    svc = GenerationService(MockAdapter())
    output = await svc.generate(
        intent="Follow up after the client meeting",
        key_facts=[
            "Pilot starts May 12",
            "Revised pricing by Friday",
            "Need confirmation on data access",
        ],
        tone="formal",
        prompt_version="advanced_v1",
        model_id="mock-sonnet",
    )
    assert len(output.fact_coverage) == 3
    assert all("fact" in c and "included" in c for c in output.fact_coverage)


@pytest.mark.asyncio
async def test_service_verifies_coverage_claims():
    """The service must not trust the model's fact_coverage blindly —
    it must verify that claimed-included facts actually appear."""
    from app.backend.services.generation import _ensure_fact_coverage

    facts = ["Pilot starts May 12", "Budget is 100k"]
    body = "We will kick the pilot off on May 12 next month."
    # The model claims both included; verification should flag the second as missing.
    claims = [
        {"fact": "Pilot starts May 12", "included": True, "evidence": "May 12"},
        {"fact": "Budget is 100k", "included": True, "evidence": "budget"},
    ]
    result = _ensure_fact_coverage(facts, body, claims)
    assert result[0]["included"] is True
    assert result[1]["included"] is False
