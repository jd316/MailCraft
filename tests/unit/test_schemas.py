"""Input validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.backend.core.schemas import GenerateRequest


def test_valid_request():
    req = GenerateRequest(
        intent="Follow up after meeting",
        key_facts=["Pilot starts May 12", "Pricing by Friday"],
        tone="formal",
    )
    assert req.prompt_version == "advanced_v1"


def test_empty_facts_rejected():
    with pytest.raises(ValidationError):
        GenerateRequest(intent="x", key_facts=[], tone="formal")


def test_empty_fact_rejected():
    with pytest.raises(ValidationError):
        GenerateRequest(intent="xyz", key_facts=["ok", " "], tone="formal")


def test_control_characters_stripped():
    req = GenerateRequest(
        intent="Follow\x00 up",
        key_facts=["fact\x01 one"],
        tone="formal",
    )
    assert "\x00" not in req.intent
    assert "\x01" not in req.key_facts[0]


def test_tone_canonicalized_to_lowercase():
    req = GenerateRequest(
        intent="hello world",
        key_facts=["one"],
        tone="FORMAL",
    )
    assert req.tone == "formal"


def test_intent_length_enforced():
    with pytest.raises(ValidationError):
        GenerateRequest(intent="ab", key_facts=["a"], tone="formal")


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate(
            {"intent": "hello", "key_facts": ["x"], "tone": "formal", "evil": 1}
        )
