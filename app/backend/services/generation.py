"""Email generation service — orchestrates prompt build, model call, parsing,
fact-coverage analysis, and persistence.

Responsibilities:
- build the request via the prompt builder
- invoke the LLM adapter (with one retry already baked into the adapter)
- parse the JSON response robustly (many models prefix/suffix content)
- compute or validate fact coverage defensively so the response is always
  complete even if the model omitted that field
- persist the draft
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass

from app.backend.core.config import get_settings
from app.backend.core.errors import GenerationTimeout, UpstreamError
from app.backend.core.logging import get_logger
from app.backend.evaluation.fact_matching import fact_included
from app.backend.llm.base import LLMAdapter
from app.backend.prompts.builder import build_generation_request

log = get_logger("services.generation")

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(slots=True)
class GenerationOutput:
    draft_id: str
    subject_suggestion: str
    email_body: str
    fact_coverage: list[dict]
    prompt_version: str
    model_id: str
    latency_ms: int
    raw_text: str


def _parse_model_json(text: str) -> dict:
    """Best-effort extraction of the JSON object from the model's text.

    Handles: raw JSON, markdown-fenced JSON, JSON buried in prose/reasoning,
    and multiple JSON-like blocks (picks the one with expected keys).
    """
    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try greedy match (first { to last })
    m = _JSON_BLOCK.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    # Try all { positions -- find the valid JSON block containing expected keys
    for i, ch in enumerate(text):
        if ch == '{':
            # Find matching closing brace by scanning backwards from end
            for j in range(len(text) - 1, i, -1):
                if text[j] == '}':
                    candidate = text[i:j + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict) and (
                            "email_body" in parsed or "subject_suggestion" in parsed
                        ):
                            return parsed
                    except json.JSONDecodeError:
                        continue
    # Last resort: try to find any valid JSON dict
    for i, ch in enumerate(text):
        if ch == '{':
            for j in range(len(text) - 1, i, -1):
                if text[j] == '}':
                    try:
                        parsed = json.loads(text[i:j + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        continue
    raise UpstreamError("model returned empty or non-JSON content", details={"preview": text[:500]})


def _ensure_fact_coverage(facts: list[str], email_body: str, existing: list | None) -> list[dict]:
    """Trust the model's coverage claims only after verifying them.

    If the model's `included: true` fact text is not actually in the email,
    flip to false. Missing entries are re-computed via the fact matcher so
    the response always has one entry per input fact, in input order.
    """
    by_fact: dict[str, dict] = {}
    if isinstance(existing, list):
        for item in existing:
            if isinstance(item, dict) and "fact" in item:
                by_fact[item["fact"].strip()] = item

    result: list[dict] = []
    for fact in facts:
        claimed = by_fact.get(fact.strip())
        included, evidence = fact_included(fact, email_body)
        if claimed is not None:
            claimed_included = bool(claimed.get("included"))
            # Verify the model's claim — downgrade false positives.
            if claimed_included and not included:
                result.append({"fact": fact, "included": False, "evidence": None})
            else:
                result.append(
                    {
                        "fact": fact,
                        "included": claimed_included and included,
                        "evidence": claimed.get("evidence") if claimed_included else None,
                    }
                )
        else:
            result.append({"fact": fact, "included": included, "evidence": evidence})
    return result


class GenerationService:
    def __init__(self, adapter: LLMAdapter) -> None:
        self.adapter = adapter

    async def generate(
        self,
        *,
        intent: str,
        key_facts: list[str],
        tone: str,
        prompt_version: str,
        model_id: str | None,
        revision_instruction: str | None = None,
        prior_draft: str | None = None,
    ) -> GenerationOutput:
        settings = get_settings()
        effective_model = model_id or settings.model_primary

        request, template = build_generation_request(
            intent=intent,
            key_facts=key_facts,
            tone=tone,
            revision_instruction=revision_instruction,
            prompt_version=prompt_version,
            model_id=effective_model,
            prior_draft=prior_draft,
        )

        # Fallback model support per docs/03 §9: try primary; on upstream or
        # timeout error, retry once against MODEL_FALLBACK if configured.
        try:
            response = await self.adapter.complete(request)
        except (UpstreamError, GenerationTimeout) as exc:
            fallback = settings.model_fallback
            if fallback and fallback != effective_model:
                log.warning(
                    "generation.fallback",
                    primary=effective_model,
                    fallback=fallback,
                    error=str(exc),
                )
                request.model = fallback
                response = await self.adapter.complete(request)
                effective_model = fallback
            else:
                raise

        parsed = _parse_model_json(response.text)

        subject = str(parsed.get("subject_suggestion") or "").strip()
        body = str(parsed.get("email_body") or "").strip()
        if not body:
            raise UpstreamError("model produced empty email_body")

        coverage = _ensure_fact_coverage(key_facts, body, parsed.get("fact_coverage"))

        output = GenerationOutput(
            draft_id=f"draft_{uuid.uuid4().hex[:16]}",
            subject_suggestion=subject,
            email_body=body,
            fact_coverage=coverage,
            prompt_version=template.version,
            model_id=response.model or effective_model,
            latency_ms=response.latency_ms,
            raw_text=response.text,
        )
        log.info(
            "generation.completed",
            prompt_version=template.version,
            model=output.model_id,
            latency_ms=output.latency_ms,
            facts_covered=sum(1 for c in coverage if c["included"]),
            facts_total=len(coverage),
        )
        return output
