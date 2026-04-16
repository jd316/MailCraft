"""Tests for the generation service's JSON parsing fallbacks and model fallback."""

from __future__ import annotations

import os

import pytest

from app.backend.core.config import get_settings
from app.backend.core.errors import UpstreamError
from app.backend.llm.base import LLMAdapter, LLMRequest, LLMResponse
from app.backend.services.generation import GenerationService, _parse_model_json


def test_parses_plain_json():
    data = _parse_model_json('{"email_body": "hi", "subject_suggestion": "s"}')
    assert data["email_body"] == "hi"


def test_parses_fenced_json():
    text = '```json\n{"email_body": "hi", "subject_suggestion": "s"}\n```'
    data = _parse_model_json(text)
    assert data["subject_suggestion"] == "s"


def test_extracts_json_from_prose_wrapper():
    text = 'Here is the JSON:\n{"email_body": "hi", "subject_suggestion": "s"}\n-- done.'
    data = _parse_model_json(text)
    assert data["email_body"] == "hi"


def test_raises_on_non_json():
    with pytest.raises(UpstreamError):
        _parse_model_json("sorry I cannot comply")


class _FlakyAdapter(LLMAdapter):
    """Fails once with UpstreamError, then succeeds. Used to test the
    fallback-model path in GenerationService.generate."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request.model)
        if len(self.calls) == 1:
            raise UpstreamError("primary down")
        return LLMResponse(
            text='{"subject_suggestion": "s", "email_body": "Dear team,\\n\\nhi.\\n\\nRegards,\\nA",'
            '"fact_coverage": [{"fact": "A", "included": true, "evidence": "A"}]}',
            model=request.model,
            usage={},
            latency_ms=0,
        )


@pytest.mark.asyncio
async def test_generation_falls_back_on_upstream_error(monkeypatch):
    monkeypatch.setenv("MODEL_FALLBACK", "claude-haiku-4-5-20251001")
    get_settings.cache_clear()
    try:
        adapter = _FlakyAdapter()
        svc = GenerationService(adapter)
        output = await svc.generate(
            intent="Follow up",
            key_facts=["A"],
            tone="formal",
            prompt_version="advanced_v1",
            model_id="claude-sonnet-4-6",
        )
        assert output.model_id == "claude-haiku-4-5-20251001"
        assert adapter.calls == ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
    finally:
        os.environ.pop("MODEL_FALLBACK", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_generation_raises_without_fallback():
    get_settings.cache_clear()
    adapter = _FlakyAdapter()  # first call fails; no fallback → bubble up
    svc = GenerationService(adapter)
    with pytest.raises(UpstreamError):
        await svc.generate(
            intent="Follow up",
            key_facts=["A"],
            tone="formal",
            prompt_version="advanced_v1",
            model_id="claude-sonnet-4-6",
        )
