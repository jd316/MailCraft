"""Tests for metrics edge cases — judge JSON parsing, empty email, weighted_total."""

from __future__ import annotations

from app.backend.evaluation.metrics import _parse_judge_json, weighted_total, METRIC_WEIGHTS


class TestParseJudgeJson:
    def test_clean_json(self):
        result = _parse_judge_json('{"score": 0.75, "rationale": "ok"}')
        assert result["score"] == 0.75

    def test_markdown_fenced(self):
        result = _parse_judge_json('```json\n{"score": 1.0, "rationale": "good"}\n```')
        assert result["score"] == 1.0

    def test_json_in_prose(self):
        result = _parse_judge_json('Here is my assessment:\n{"score": 0.5, "rationale": "mixed"}\nEnd.')
        assert result["score"] == 0.5

    def test_invalid_returns_empty(self):
        result = _parse_judge_json("This is not JSON at all")
        assert result == {}

    def test_empty_returns_empty(self):
        result = _parse_judge_json("")
        assert result == {}

    def test_partial_json_returns_empty(self):
        result = _parse_judge_json('{"score": ')
        assert result == {}


class TestWeightedTotal:
    def test_normal(self):
        scores = {"fact_inclusion": 1.0, "tone_alignment": 1.0, "professional_quality": 1.0}
        assert weighted_total(scores) == 1.0

    def test_zero(self):
        scores = {"fact_inclusion": 0.0, "tone_alignment": 0.0, "professional_quality": 0.0}
        assert weighted_total(scores) == 0.0

    def test_empty_scores(self):
        assert weighted_total({}) == 0.0

    def test_partial_scores(self):
        scores = {"fact_inclusion": 1.0}
        result = weighted_total(scores)
        # Normalizes: (0.45 * 1.0) / 0.45 = 1.0
        assert result == 1.0


class TestStructuralQuality:
    def test_empty_email(self):
        from app.backend.evaluation.metrics import _structural_quality
        score, details = _structural_quality("")
        assert score == 0.0

    def test_full_email(self):
        from app.backend.evaluation.metrics import _structural_quality
        email = "Dear Team,\n\nThis is the body of the email with enough content to pass the length check. " * 5 + "\n\nBest regards,\nAlex"
        score, details = _structural_quality(email)
        assert score > 0.5
