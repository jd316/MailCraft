"""Tests for _parse_model_json edge cases and _ensure_fact_coverage."""

from __future__ import annotations

import pytest

from app.backend.core.errors import UpstreamError
from app.backend.services.generation import _parse_model_json, _ensure_fact_coverage


class TestParseModelJson:
    def test_raw_json(self):
        result = _parse_model_json('{"subject_suggestion":"s","email_body":"b"}')
        assert result["subject_suggestion"] == "s"

    def test_markdown_fenced(self):
        text = '```json\n{"subject_suggestion":"s","email_body":"b"}\n```'
        result = _parse_model_json(text)
        assert result["email_body"] == "b"

    def test_json_in_prose(self):
        text = 'Here is the email:\n\n{"subject_suggestion":"s","email_body":"Dear team"}\n\nDone.'
        result = _parse_model_json(text)
        assert result["email_body"] == "Dear team"

    def test_multiple_braces_picks_email(self):
        text = '{"reasoning": "I thought about it"}\n\n{"subject_suggestion":"s","email_body":"b"}'
        result = _parse_model_json(text)
        assert "email_body" in result

    def test_empty_raises(self):
        with pytest.raises(UpstreamError, match="empty or non-JSON"):
            _parse_model_json("")

    def test_no_json_raises(self):
        with pytest.raises(UpstreamError, match="empty or non-JSON"):
            _parse_model_json("This is just prose with no JSON at all.")

    def test_invalid_json_in_braces(self):
        with pytest.raises(UpstreamError):
            _parse_model_json("Some text {broken json here} end")

    def test_whitespace_only(self):
        with pytest.raises(UpstreamError):
            _parse_model_json("   \n\n   ")


class TestEnsureFactCoverage:
    def test_model_claims_verified(self):
        facts = ["Budget approved"]
        body = "The budget has been approved for Q3."
        existing = [{"fact": "Budget approved", "included": True, "evidence": "budget has been approved"}]
        result = _ensure_fact_coverage(facts, body, existing)
        assert result[0]["included"] is True

    def test_false_positive_downgraded(self):
        facts = ["Meeting on May 15"]
        body = "Thank you for your email. Best regards."
        existing = [{"fact": "Meeting on May 15", "included": True, "evidence": "May 15"}]
        result = _ensure_fact_coverage(facts, body, existing)
        assert result[0]["included"] is False
        assert result[0]["evidence"] is None

    def test_missing_coverage_recomputed(self):
        facts = ["Budget approved"]
        body = "The budget has been approved."
        result = _ensure_fact_coverage(facts, body, None)
        assert len(result) == 1
        assert result[0]["fact"] == "Budget approved"

    def test_empty_existing_list(self):
        facts = ["Fact one"]
        body = "This email mentions fact one clearly."
        result = _ensure_fact_coverage(facts, body, [])
        assert len(result) == 1
