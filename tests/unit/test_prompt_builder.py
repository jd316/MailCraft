"""Unit tests for the prompt builder and registry."""

from __future__ import annotations

import pytest

from app.backend.core.errors import NotFound
from app.backend.prompts.builder import build_generation_request
from app.backend.prompts.registry import list_versions, load_prompt


def test_registry_lists_both_versions():
    versions = list_versions()
    assert "baseline_v1" in versions
    assert "advanced_v1" in versions


def test_unknown_version_raises():
    with pytest.raises(NotFound):
        load_prompt("does_not_exist")


def test_advanced_prompt_has_strategy_marker():
    template = load_prompt("advanced_v1")
    assert "ADVANCED-STRATEGY" in template.system_text


def test_builder_injects_brief_json():
    req, template = build_generation_request(
        intent="Follow up",
        key_facts=["A", "B"],
        tone="formal",
        revision_instruction=None,
        prompt_version="advanced_v1",
        model_id="claude-sonnet-4-6",
    )
    user = req.messages[0].content
    assert "```json" in user
    assert "\"intent\": \"Follow up\"" in user
    assert "\"A\"" in user
    assert template.version == "advanced_v1"


def test_builder_includes_revision_when_provided():
    req, _ = build_generation_request(
        intent="Follow up",
        key_facts=["A"],
        tone="casual",
        revision_instruction="Make it shorter",
        prompt_version="baseline_v1",
        model_id="claude-sonnet-4-6",
        prior_draft="Hi there, ...",
    )
    user = req.messages[0].content
    assert "Previous draft" in user
    assert "Make it shorter" in user
