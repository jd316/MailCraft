"""Three custom evaluation metrics for MailCraft.

Each metric returns a `MetricScore` in the 0.0–1.0 range and a short rationale.

1. **Fact Inclusion Score** — deterministic, rule-based (docs/06 §4.1).
2. **Tone Alignment Score** — LLM-as-judge with a fixed rubric (docs/06 §4.2).
3. **Professional Quality Score** — hybrid: deterministic structural checks
   combined with an LLM-judge clarity/fluency score (docs/06 §4.3).

The LLM-judge prompts are tagged with `JUDGE-RUBRIC` and the metric name so the
a test-only mock adapter can produce plausible scores for CI.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.backend.core.config import get_settings
from app.backend.core.logging import get_logger
from app.backend.evaluation.fact_matching import fact_inclusion_score
from app.backend.llm.base import LLMAdapter, LLMMessage, LLMRequest

log = get_logger("eval.metrics")

# ---------------------------------------------------------------------------
# Common types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MetricScore:
    name: str
    score: float
    rationale: str
    details: dict | None = None


# ---------------------------------------------------------------------------
# Metric 1 — Fact Inclusion Score (deterministic)
# ---------------------------------------------------------------------------


def fact_inclusion_metric(*, key_facts: list[str], email_body: str) -> MetricScore:
    score, per_fact = fact_inclusion_score(key_facts, email_body)
    missing = [p["fact"] for p in per_fact if not p["included"]]
    rationale = (
        f"{sum(1 for p in per_fact if p['included'])}/{len(per_fact)} facts detected."
        + (f" Missing: {missing}." if missing else "")
    )
    return MetricScore(
        name="fact_inclusion",
        score=round(score, 4),
        rationale=rationale,
        details={"per_fact": per_fact},
    )


# ---------------------------------------------------------------------------
# Metric 2 — Tone Alignment Score (LLM-as-judge with rubric)
# ---------------------------------------------------------------------------

_TONE_JUDGE_SYSTEM = """You are an editorial judge scoring an email for TONE ALIGNMENT.
You must follow a strict rubric and return a single JSON object.

JUDGE-RUBRIC: tone_alignment

Rubric (anchor scores — choose the closest):
- 1.00 → strong match: register, word choice, greeting/closing, and overall
  stance unambiguously reflect the requested tone; no contradictory cues.
- 0.75 → mostly correct: minor lapses (one slightly off phrase or a mildly
  mismatched greeting/closing) but the dominant impression matches.
- 0.50 → mixed: clear tonal contradictions; the reader could not classify
  the email confidently as the requested tone.
- 0.25 → weak match: only a surface-level nod to the requested tone;
  dominant impression is different.
- 0.00 → wrong tone: the email signals a different tone entirely.

Scoring criteria (all must be evaluated):
1. Greeting/closing appropriateness for the tone.
2. Register (word choice, sentence rhythm) for the tone.
3. Emotional stance / politeness / urgency where applicable.
4. Absence of jarring register shifts.

Return ONLY valid JSON with these keys:
{ "score": <float in [0,1]>, "rationale": "<1-2 sentence explanation>" }
"""


_QUALITY_JUDGE_SYSTEM = """You are an editorial judge scoring an email for PROFESSIONAL QUALITY.
Return a single JSON object.

JUDGE-RUBRIC: professional_quality

Score each sub-criterion on [0,1], then report the mean as `score`:
- clarity: easy to read on first pass, no vague pronouns, no run-on sentences.
- fluency: grammatical, natural English, no awkward phrasing.
- actionability: the next step (if relevant) is explicit.
- cohesion: greeting → body → closing flow without repetition.

Return ONLY valid JSON:
{ "score": <float in [0,1]>, "rationale": "<1-2 sentence explanation>", "sub_scores": {"clarity": <float>, "fluency": <float>, "actionability": <float>, "cohesion": <float>} }
"""


def _build_judge_request(
    *, system_text: str, payload: dict, model: str | None = None
) -> LLMRequest:
    settings = get_settings()
    return LLMRequest(
        model=model or settings.model_judge,
        system=system_text,
        messages=[
            LLMMessage(
                role="user",
                content="```json\n" + json.dumps(payload, indent=2) + "\n```",
            )
        ],
        temperature=0.0,
        max_tokens=400,
        timeout_seconds=settings.gen_timeout_seconds,
        response_format="json",
    )


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_judge_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def _clip(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


async def tone_alignment_metric(
    adapter: LLMAdapter,
    *,
    tone: str,
    subject: str,
    email_body: str,
    judge_model: str | None = None,
) -> MetricScore:
    payload = {
        "requested_tone": tone,
        "subject": subject,
        "email_body": email_body,
    }
    response = await adapter.complete(
        _build_judge_request(system_text=_TONE_JUDGE_SYSTEM, payload=payload, model=judge_model)
    )
    parsed = _parse_judge_json(response.text)
    score = _clip(parsed.get("score", 0.0))
    rationale = str(parsed.get("rationale", "")).strip() or "no rationale"
    return MetricScore(
        name="tone_alignment",
        score=round(score, 4),
        rationale=rationale,
        details={"judge_raw": response.text[:500]},
    )


# Structural checks for the quality metric — cheap and deterministic.
_GREETING_RE = re.compile(
    r"^\s*(dear|hi|hello|hey|greetings|good\s+(?:morning|afternoon|evening)|team)\b",
    re.IGNORECASE,
)
_CLOSING_RE = re.compile(
    r"(best|kind\s+regards|regards|sincerely|thanks|thank\s+you|cheers|with\s+appreciation|warm\s+regards|respectfully)[,.\s]",
    re.IGNORECASE,
)


def _structural_quality(email_body: str) -> tuple[float, dict]:
    lines = [ln for ln in (email_body or "").splitlines() if ln.strip()]
    if not lines:
        return 0.0, {"reason": "empty"}

    first_line = lines[0]
    last_chunk = "\n".join(lines[-3:])

    checks = {
        "has_greeting": bool(_GREETING_RE.search(first_line)),
        "has_closing": bool(_CLOSING_RE.search(last_chunk)),
        "length_ok": 180 <= len(email_body) <= 2200,
        "paragraphs": email_body.count("\n\n") >= 1,
        "no_obvious_placeholder": not re.search(r"\[[^\]]+\]", email_body),
    }
    score = sum(1 for v in checks.values() if v) / len(checks)
    return score, checks


async def professional_quality_metric(
    adapter: LLMAdapter,
    *,
    subject: str,
    email_body: str,
    judge_model: str | None = None,
) -> MetricScore:
    structural_score, structural = _structural_quality(email_body)

    judge_payload = {
        "subject": subject,
        "email_body": email_body,
    }
    response = await adapter.complete(
        _build_judge_request(system_text=_QUALITY_JUDGE_SYSTEM, payload=judge_payload, model=judge_model)
    )
    parsed = _parse_judge_json(response.text)
    judge_score = _clip(parsed.get("score", 0.0))
    sub_scores = parsed.get("sub_scores") or {}

    # 60% judge, 40% structural — structural protects against fluent-but-malformed.
    final = round(0.6 * judge_score + 0.4 * structural_score, 4)
    rationale = (
        str(parsed.get("rationale", "")).strip()
        + f" | structural={structural_score:.2f} checks={structural}"
    )
    return MetricScore(
        name="professional_quality",
        score=final,
        rationale=rationale.strip(),
        details={
            "judge_score": judge_score,
            "structural_score": round(structural_score, 4),
            "structural_checks": structural,
            "sub_scores": sub_scores,
        },
    )


# ---------------------------------------------------------------------------
# Weighting for the overall score — matches docs/06 §9
# ---------------------------------------------------------------------------

METRIC_WEIGHTS: dict[str, float] = {
    "fact_inclusion": 0.45,
    "tone_alignment": 0.25,
    "professional_quality": 0.30,
}


def weighted_total(scores: dict[str, float]) -> float:
    total = 0.0
    weight_sum = 0.0
    for name, weight in METRIC_WEIGHTS.items():
        if name in scores:
            total += weight * scores[name]
            weight_sum += weight
    if weight_sum == 0:
        return 0.0
    return round(total / weight_sum, 4)
