"""Google Gemini adapter — uses the google-genai SDK."""

from __future__ import annotations

import asyncio
import time

from google import genai
from google.genai import types

from app.backend.core.config import get_settings
from app.backend.core.errors import GenerationTimeout, UpstreamError
from app.backend.core.logging import get_logger
from app.backend.llm.base import LLMAdapter, LLMRequest, LLMResponse

log = get_logger("llm.gemini")

# Gemini thinking models consume max_output_tokens for both reasoning and
# output. We set a generous floor so the thinking budget never starves the
# actual response.
_MIN_OUTPUT_TOKENS = 8192


class GeminiAdapter(LLMAdapter):
    def __init__(self) -> None:
        settings = get_settings()
        api_key = settings.google_api_key
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY is required for the gemini provider.")
        self._client = genai.Client(api_key=api_key)

    def _invoke(self, request: LLMRequest) -> tuple[str, dict[str, int]]:
        effective_max = max(request.max_tokens, _MIN_OUTPUT_TOKENS)

        config = types.GenerateContentConfig(
            system_instruction=request.system,
            temperature=request.temperature,
            max_output_tokens=effective_max,
        )
        if request.response_format == "json":
            config.response_mime_type = "application/json"

        contents = []
        for msg in request.messages:
            contents.append(
                types.Content(
                    role="user" if msg.role == "user" else "model",
                    parts=[types.Part(text=msg.content)],
                )
            )

        try:
            response = self._client.models.generate_content(
                model=request.model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            error_msg = str(exc)
            if "timeout" in error_msg.lower() or "deadline" in error_msg.lower():
                raise GenerationTimeout("Gemini request timed out") from exc
            raise UpstreamError(f"Gemini error: {error_msg}") from exc

        text = response.text or ""
        usage_meta = response.usage_metadata
        usage = {
            "input_tokens": getattr(usage_meta, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(usage_meta, "candidates_token_count", 0) or 0,
        }
        return text, usage

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        try:
            text, usage = await asyncio.to_thread(self._invoke, request)
        except (GenerationTimeout, UpstreamError):
            raise
        except Exception as exc:
            raise UpstreamError(f"Gemini error: {exc}") from exc

        latency_ms = int((time.perf_counter() - start) * 1000)

        log.info(
            "gemini.completion",
            model=request.model,
            latency_ms=latency_ms,
            **usage,
        )

        return LLMResponse(
            text=text,
            model=request.model,
            usage=usage,
            latency_ms=latency_ms,
        )
