"""Build the final LLM request from a user brief and prompt version.

Keeping this pure (no I/O beyond the registry) makes the prompt surface
easy to unit-test and diff against golden fixtures.
"""

from __future__ import annotations

import json

from app.backend.core.config import get_settings
from app.backend.llm.base import LLMMessage, LLMRequest
from app.backend.prompts.registry import PromptTemplate, load_prompt


def build_generation_request(
    *,
    intent: str,
    key_facts: list[str],
    tone: str,
    revision_instruction: str | None,
    prompt_version: str,
    model_id: str,
    prior_draft: str | None = None,
) -> tuple[LLMRequest, PromptTemplate]:
    settings = get_settings()
    template = load_prompt(prompt_version)

    brief = {
        "intent": intent,
        "key_facts": key_facts,
        "tone": tone,
    }

    user_parts: list[str] = ["Brief:\n```json\n" + json.dumps(brief, indent=2) + "\n```"]
    if prior_draft:
        user_parts.append(
            "Previous draft to revise:\n```text\n" + prior_draft.strip() + "\n```"
        )
    if revision_instruction:
        user_parts.append(f"Revision instruction: {revision_instruction.strip()}")

    user_parts.append(
        "Produce the final JSON response now. Do not include markdown fences "
        "or any commentary before or after the JSON."
    )

    messages = [LLMMessage(role="user", content="\n\n".join(user_parts))]

    request = LLMRequest(
        model=model_id,
        system=template.system_text,
        messages=messages,
        temperature=settings.gen_temperature,
        max_tokens=settings.gen_max_tokens,
        timeout_seconds=settings.gen_timeout_seconds,
        response_format="json",
    )
    return request, template
