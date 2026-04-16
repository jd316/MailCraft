"""Tests for the deterministic mock adapter."""

from __future__ import annotations

import json

import pytest

from app.backend.llm.base import LLMMessage, LLMRequest
from app.backend.llm.mock_adapter import MockAdapter


def _build(system: str, payload: dict) -> LLMRequest:
    user_content = "```json\n" + json.dumps(payload) + "\n```"
    return LLMRequest(
        model="mock-model",
        system=system,
        messages=[LLMMessage(role="user", content=user_content)],
    )


@pytest.mark.asyncio
async def test_advanced_prompt_returns_weaving_body():
    adapter = MockAdapter()
    request = _build(
        "ADVANCED-STRATEGY-v1",
        {"intent": "Follow up", "key_facts": ["A is 1", "B is 2"], "tone": "formal"},
    )
    res = await adapter.complete(request)
    data = json.loads(res.text)
    # The advanced branch weaves facts into prose; baseline branch bullets them.
    assert "- A is 1" not in data["email_body"]
    assert "A is 1" in data["email_body"]


@pytest.mark.asyncio
async def test_baseline_can_drop_last_fact():
    """The baseline mock may drop the last fact for ~35% of seeds.
    Verify the mechanism exists across many inputs — not a single run.
    """
    adapter = MockAdapter()
    dropped = 0
    for i in range(30):
        request = _build(
            "baseline prompt",  # missing the ADVANCED marker
            {
                "intent": f"Intent {i}",
                "key_facts": [f"fact {i}-1", f"fact {i}-2", f"fact {i}-3", f"last fact {i}"],
                "tone": "formal",
            },
        )
        res = await adapter.complete(request)
        data = json.loads(res.text)
        if not data["fact_coverage"][-1]["included"]:
            dropped += 1
    # Expect at least some drops across 30 seeds.
    assert 1 <= dropped <= 25, dropped


@pytest.mark.asyncio
async def test_judge_rubric_returns_score_and_rationale():
    adapter = MockAdapter()
    request = LLMRequest(
        model="mock-judge",
        system="JUDGE-RUBRIC: tone_alignment",
        messages=[LLMMessage(role="user", content="payload")],
    )
    res = await adapter.complete(request)
    data = json.loads(res.text)
    assert 0.0 <= data["score"] <= 1.0
    assert data["rationale"]
