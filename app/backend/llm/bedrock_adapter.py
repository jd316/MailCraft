"""AWS Bedrock adapter — calls Claude/Mistral/Nova/Meta models via the
Bedrock Runtime API using the standard Messages-style request body.

Uses boto3 async-compatible sync client wrapped in asyncio.to_thread so the
rest of the app stays fully async. Retries transient errors (throttling,
5xx) with exponential backoff via tenacity.

Supports two body formats:
- **Anthropic** (claude): `anthropic_version` + `messages`
- **Messages-compatible** (mistral, nova, deepseek): `messages` + `max_tokens`

The adapter auto-detects the format from the model ID prefix.
"""

from __future__ import annotations

import asyncio
import json
import time

import boto3
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.backend.core.config import get_settings
from app.backend.core.errors import GenerationTimeout, UpstreamError
from app.backend.core.logging import get_logger
from app.backend.llm.base import LLMAdapter, LLMRequest, LLMResponse

log = get_logger("llm.bedrock")


def _is_anthropic(model_id: str) -> bool:
    return "anthropic" in model_id.lower()


def _build_body(request: LLMRequest) -> dict:
    if _is_anthropic(request.model):
        return {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
    # Mistral / Nova / Meta / DeepSeek — messages-compatible format.
    messages = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    for m in request.messages:
        messages.append({"role": m.role, "content": m.content})
    return {
        "messages": messages,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
    }


def _parse_response(model_id: str, body: dict) -> str:
    """Extract the text from the model-specific response shape."""
    # Anthropic
    if "content" in body and isinstance(body["content"], list):
        parts = []
        for block in body["content"]:
            if isinstance(block, dict) and (block.get("type") == "text" or "text" in block):
                parts.append(block["text"])
        if parts:
            return "".join(parts).strip()

    # Mistral / DeepSeek (choices[].message.content)
    if "choices" in body:
        choices = body["choices"]
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message", {})
            if isinstance(msg, dict) and "content" in msg:
                return str(msg["content"]).strip()

    # Amazon Nova (output.message.content[].text)
    if "output" in body:
        out = body["output"]
        if isinstance(out, dict) and "message" in out:
            msg = out["message"]
            if isinstance(msg, dict) and "content" in msg:
                parts = msg["content"]
                if isinstance(parts, list):
                    return "".join(p.get("text", "") for p in parts).strip()

    # Meta Llama (generation)
    if "generation" in body:
        return str(body["generation"]).strip()

    # Fallback — try to find any text
    return json.dumps(body)


def _extract_usage(model_id: str, body: dict) -> dict[str, int]:
    usage = body.get("usage", {})
    return {
        "input_tokens": usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or usage.get("completion_tokens", 0) or 0,
    }


class BedrockAdapter(LLMAdapter):
    def __init__(self, *, region: str | None = None) -> None:
        settings = get_settings()
        self._region = region or settings.aws_region
        self._client = boto3.client("bedrock-runtime", region_name=self._region)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type(Exception),
    )
    def _invoke(self, model_id: str, body_bytes: bytes) -> dict:
        try:
            resp = self._client.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=body_bytes,
            )
            return json.loads(resp["body"].read())
        except self._client.exceptions.ThrottlingException:
            raise  # tenacity retries
        except self._client.exceptions.ModelTimeoutException as exc:
            raise GenerationTimeout("Bedrock model timed out") from exc
        except Exception as exc:
            error_msg = str(exc)
            if "ThrottlingException" in error_msg or "TooManyRequestsException" in error_msg:
                raise  # tenacity retries
            if "TimeoutException" in error_msg or "timed out" in error_msg.lower():
                raise GenerationTimeout("Bedrock model timed out") from exc
            raise UpstreamError(
                f"Bedrock invocation failed: {error_msg}",
                details={"model_id": model_id},
            ) from exc

    async def complete(self, request: LLMRequest) -> LLMResponse:
        body = _build_body(request)
        body_bytes = json.dumps(body).encode()
        start = time.perf_counter()

        try:
            result = await asyncio.to_thread(self._invoke, request.model, body_bytes)
        except GenerationTimeout:
            raise
        except UpstreamError:
            raise
        except Exception as exc:
            raise UpstreamError(f"Bedrock error: {exc}") from exc

        latency_ms = int((time.perf_counter() - start) * 1000)
        text = _parse_response(request.model, result)
        usage = _extract_usage(request.model, result)

        log.info(
            "bedrock.completion",
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
