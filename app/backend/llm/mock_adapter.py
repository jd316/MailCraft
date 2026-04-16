"""Deterministic mock LLM adapter for tests and offline runs.

Produces realistic-looking JSON email outputs based on the inputs so the
evaluation harness exercises real parsing/metric code paths. Respects the
prompt_version signal encoded in the system prompt to vary outputs between
the baseline and advanced strategies — this keeps the comparison meaningful
even without a network call.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time

from app.backend.llm.base import LLMAdapter, LLMRequest, LLMResponse

# Tone styles influence greeting and sign-off vocabulary.
_GREETINGS = {
    "formal": "Dear {recipient},",
    "casual": "Hi {recipient},",
    "urgent": "{recipient},",
    "empathetic": "Dear {recipient},",
    "friendly": "Hi {recipient},",
    "assertive": "{recipient},",
    "apologetic": "Dear {recipient},",
    "enthusiastic": "Hi {recipient}!",
    "neutral": "Hello {recipient},",
}

_CLOSINGS = {
    "formal": "Best regards,\nThe Team",
    "casual": "Thanks,\nThe Team",
    "urgent": "Please confirm as soon as possible.\n\nThe Team",
    "empathetic": "With sincere regards,\nThe Team",
    "friendly": "Cheers,\nThe Team",
    "assertive": "Regards,\nThe Team",
    "apologetic": "With our apologies,\nThe Team",
    "enthusiastic": "Looking forward to next steps!\n\nThe Team",
    "neutral": "Regards,\nThe Team",
}


def _parse_user_content(content: str) -> dict:
    """The prompt builder always embeds a JSON block with the user's fields."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {}


def _baseline_body(intent: str, facts: list[str], tone: str) -> tuple[str, str]:
    subject = f"{intent.rstrip('.').title()}"
    greeting = _GREETINGS.get(tone, _GREETINGS["neutral"]).format(recipient="Team")
    bullets = "\n".join(f"- {fact}" for fact in facts)
    body = (
        f"{greeting}\n\n"
        f"I wanted to reach out regarding: {intent}.\n\n"
        f"Key points:\n{bullets}\n\n"
        f"Let me know if you have any questions.\n\n"
        f"{_CLOSINGS.get(tone, _CLOSINGS['neutral'])}"
    )
    return subject, body


def _advanced_body(intent: str, facts: list[str], tone: str) -> tuple[str, str]:
    subject = f"{intent.rstrip('.').title()} — next steps"
    greeting = _GREETINGS.get(tone, _GREETINGS["neutral"]).format(recipient="Team")

    # Weave facts into prose rather than bulleting them — mirrors the
    # advanced prompt strategy described in docs/06_EVALUATION_PLAN.md.
    weaving = " ".join(
        f"{fact.rstrip('.')}."
        if not fact.endswith((".", "!", "?"))
        else fact
        for fact in facts
    )
    body = (
        f"{greeting}\n\n"
        f"Thank you for your time on this. Following up on {intent.lower().rstrip('.')}: "
        f"{weaving} "
        f"I'd appreciate your confirmation so we can move forward on the agreed timeline.\n\n"
        f"Please let me know if anything above needs adjustment.\n\n"
        f"{_CLOSINGS.get(tone, _CLOSINGS['neutral'])}"
    )
    return subject, body


class MockAdapter(LLMAdapter):
    """Deterministic adapter keyed by (model, prompt) hash."""

    def __init__(self, *, deterministic: bool = True) -> None:
        self._deterministic = deterministic

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"),
            "",
        )
        payload = _parse_user_content(last_user)
        intent = payload.get("intent", "follow up")
        facts = payload.get("key_facts") or []
        tone = (payload.get("tone") or "neutral").lower()

        # System prompt encodes the strategy — pick output shape accordingly.
        is_advanced = "ADVANCED-STRATEGY" in request.system

        if is_advanced:
            subject, body = _advanced_body(intent, facts, tone)
        else:
            subject, body = _baseline_body(intent, facts, tone)

        # Judge/metric prompts ask for JSON scores. Detect and answer.
        if "JUDGE-RUBRIC" in request.system:
            answer = _judge_response(request.system, last_user, payload)
            return LLMResponse(
                text=answer,
                model=request.model,
                usage={"input_tokens": 0, "output_tokens": 0},
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

        fact_coverage = [
            {"fact": fact, "included": True, "evidence": fact[:60]} for fact in facts
        ]
        out = {
            "subject_suggestion": subject,
            "email_body": body,
            "fact_coverage": fact_coverage,
        }
        text = json.dumps(out)

        # Introduce a small deterministic jitter so the baseline sometimes
        # drops the last fact (demonstrates metric sensitivity in eval runs).
        # Non-cryptographic: SHA-256 as a stable hash; random.Random as a
        # seeded PRNG for reproducibility. Nothing here depends on secrecy.
        digest = hashlib.sha256((request.model + last_user).encode()).hexdigest()
        seed = int(digest, 16)
        # random.Random is used here purely for deterministic test fixtures
        # (eval reproducibility), never for any security decision.
        rng = random.Random(seed)  # nosec B311
        if not is_advanced and facts and rng.random() < 0.35:
            # Simulate a weaker baseline: drop the last fact from the body.
            dropped = facts[-1]
            weakened_body = body.replace(f"- {dropped}\n", "").replace(f"- {dropped}", "")
            out["email_body"] = weakened_body
            out["fact_coverage"][-1]["included"] = False
            text = json.dumps(out)

        latency_ms = int((time.perf_counter() - start) * 1000)
        return LLMResponse(
            text=text,
            model=request.model,
            usage={"input_tokens": 0, "output_tokens": 0},
            latency_ms=latency_ms,
        )


def _judge_response(system: str, user: str, payload: dict) -> str:
    """Return a plausible judge JSON for the mock provider."""
    # Tone judge
    if "tone_alignment" in system:
        return json.dumps(
            {
                "score": 0.85 if "ADVANCED-STRATEGY" in user else 0.7,
                "rationale": "Greeting and closing match requested tone; body stays on-register.",
            }
        )
    # Professional quality judge
    if "professional_quality" in system:
        return json.dumps(
            {
                "score": 0.9 if "ADVANCED-STRATEGY" in user else 0.8,
                "rationale": "Clear structure with greeting, body, and closing; no grammar issues.",
            }
        )
    return json.dumps({"score": 0.8, "rationale": "ok"})
