"""Unit tests for the fact-inclusion matcher."""

from __future__ import annotations

from app.backend.evaluation.fact_matching import fact_included, fact_inclusion_score


def test_detects_number_token():
    body = "We will deliver the report on April 18 as discussed."
    ok, ev = fact_included("New delivery date is April 18", body)
    assert ok
    assert "April" in (ev or "")


def test_missing_number_token_returns_false():
    body = "We will deliver the report soon."
    ok, _ = fact_included("New delivery date is April 18", body)
    assert ok is False


def test_quoted_string_required():
    body = "The PR is blocked until we decide on a 'fast export' latency target."
    ok, _ = fact_included("Spec calls for 'fast export' with a latency target", body)
    assert ok is True


def test_quoted_string_missing_fails():
    body = "The PR is blocked until we decide on latency targets."
    ok, _ = fact_included("Spec calls for 'fast export' with a latency target", body)
    assert ok is False


def test_score_is_share_of_facts():
    facts = ["A is 42", "B is 100", "C is 7"]
    body = "A is 42 and C is 7."
    score, per = fact_inclusion_score(facts, body)
    assert score == round(2 / 3, 4) or abs(score - 2 / 3) < 1e-4
    assert [p["included"] for p in per] == [True, False, True]


def test_empty_facts_is_full_score():
    score, per = fact_inclusion_score([], "anything")
    assert score == 1.0
    assert per == []
