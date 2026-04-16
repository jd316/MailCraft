"""Unit tests for the three custom metrics."""

from __future__ import annotations

import pytest

from app.backend.evaluation.metrics import (
    METRIC_WEIGHTS,
    fact_inclusion_metric,
    professional_quality_metric,
    tone_alignment_metric,
    weighted_total,
)
from app.backend.llm.mock_adapter import MockAdapter


def test_weights_sum_to_one():
    assert round(sum(METRIC_WEIGHTS.values()), 4) == 1.0


def test_fact_inclusion_metric_rationale_lists_missing():
    result = fact_inclusion_metric(
        key_facts=["Pilot begins May 12", "Budget is 180,000 USD"],
        email_body="We'll start the pilot on May 12 shortly.",
    )
    assert 0.0 <= result.score <= 1.0
    assert "Budget" in result.rationale or "missing" in result.rationale.lower()


def test_weighted_total_honors_weights():
    total = weighted_total(
        {"fact_inclusion": 1.0, "tone_alignment": 0.5, "professional_quality": 0.8}
    )
    assert total == round(0.45 * 1.0 + 0.25 * 0.5 + 0.30 * 0.8, 4)


@pytest.mark.asyncio
async def test_tone_alignment_metric_uses_judge():
    adapter = MockAdapter()
    score = await tone_alignment_metric(
        adapter,
        tone="formal",
        subject="Follow-up",
        email_body="Dear team, thank you for your time.\n\nRegards, Alex",
    )
    assert 0.0 <= score.score <= 1.0
    assert score.name == "tone_alignment"


@pytest.mark.asyncio
async def test_professional_quality_metric_hybrid():
    adapter = MockAdapter()
    body = (
        "Dear team,\n\n"
        "Thank you for your time today. Please confirm by Friday so we can proceed.\n\n"
        "Best regards,\nAlex"
    )
    score = await professional_quality_metric(adapter, subject="Follow-up", email_body=body)
    assert 0.0 <= score.score <= 1.0
    details = score.details or {}
    assert "structural_checks" in details
