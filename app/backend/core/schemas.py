"""Pydantic request/response schemas for the public API.

Strict validation per docs/04_API_SPEC.md §3 and docs/02_SRD.md FR-09.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.backend.core.config import get_settings

SUPPORTED_TONES = {
    "formal",
    "casual",
    "urgent",
    "empathetic",
    "friendly",
    "assertive",
    "apologetic",
    "enthusiastic",
    "neutral",
}

_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize(text: str) -> str:
    """Strip dangerous control characters and normalize whitespace at boundaries."""
    return _CTRL_CHARS.sub("", text).strip()


class GenerateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    intent: str = Field(min_length=3)
    key_facts: list[str] = Field(min_length=1)
    tone: str
    revision_instruction: str | None = None
    prompt_version: str = "advanced_v1"
    model_id: str | None = None

    @field_validator("intent", "revision_instruction")
    @classmethod
    def _sanitize_text(cls, v: str | None) -> str | None:
        if v is None:
            return v
        cleaned = _sanitize(v)
        s = get_settings()
        if len(cleaned) > s.max_intent_chars:
            raise ValueError(f"intent exceeds {s.max_intent_chars} characters")
        return cleaned

    @field_validator("key_facts")
    @classmethod
    def _validate_facts(cls, v: list[str]) -> list[str]:
        s = get_settings()
        if len(v) > s.max_facts:
            raise ValueError(f"key_facts may not exceed {s.max_facts} items")
        cleaned: list[str] = []
        for idx, fact in enumerate(v):
            c = _sanitize(fact)
            if not c:
                raise ValueError(f"key_facts[{idx}] is empty")
            if len(c) > s.max_fact_chars:
                raise ValueError(f"key_facts[{idx}] exceeds {s.max_fact_chars} characters")
            cleaned.append(c)
        return cleaned

    @field_validator("tone")
    @classmethod
    def _validate_tone(cls, v: str) -> str:
        c = _sanitize(v).lower()
        if not c:
            raise ValueError("tone is required")
        # Free-form tones are allowed for flexibility; enforce length only.
        if c not in SUPPORTED_TONES and len(c) > 40:
            raise ValueError("tone label too long")
        return c


class RegenerateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    draft_id: str
    revision_instruction: str = Field(min_length=1)
    prompt_version: str | None = None
    model_id: str | None = None

    @field_validator("revision_instruction")
    @classmethod
    def _sanitize_revision(cls, v: str) -> str:
        s = get_settings()
        c = _sanitize(v)
        if len(c) > s.max_revision_chars:
            raise ValueError(f"revision_instruction exceeds {s.max_revision_chars} characters")
        return c


class FactCoverageItem(BaseModel):
    fact: str
    included: bool
    evidence: str | None = None


class GenerateResponse(BaseModel):
    request_id: str
    draft_id: str
    subject_suggestion: str
    email_body: str
    fact_coverage: list[FactCoverageItem]
    model_id: str
    prompt_version: str
    latency_ms: int


class RevisionResponse(BaseModel):
    revision_id: str
    draft_id: str
    revision_instruction: str | None
    prompt_version: str
    model_id: str
    subject_suggestion: str | None
    email_body: str
    created_at: datetime


class DraftDeletedResponse(BaseModel):
    draft_id: str
    deleted: bool = True


class DraftResponse(BaseModel):
    draft_id: str
    intent: str
    key_facts: list[str]
    tone: str
    subject_suggestion: str | None
    email_body: str
    prompt_version: str
    model_id: str
    created_at: datetime
    revisions: int


class EvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str
    prompt_version: str
    label: str | None = None


class EvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_name: str = Field(min_length=1, max_length=120)
    config_a: EvalConfig
    config_b: EvalConfig
    scenario_set_id: str = "default_10"


class EvalRunResponse(BaseModel):
    evaluation_run_id: str
    status: Literal["queued", "running", "completed", "failed"]


class EvalAveragesByConfig(BaseModel):
    fact_inclusion: float
    tone_alignment: float
    professional_quality: float
    weighted_total: float


class EvalRunResult(BaseModel):
    evaluation_run_id: str
    run_name: str
    status: Literal["queued", "running", "completed", "failed"]
    config_a: EvalConfig
    config_b: EvalConfig
    average_scores: dict[str, EvalAveragesByConfig] | None = None
    artifact_paths: dict[str, str] | None = None
    recommended_winner: str | None = None
    failure_reason: str | None = None
