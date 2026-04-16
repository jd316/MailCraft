"""Provider-agnostic LLM adapter interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class LLMMessage:
    role: str
    content: str


@dataclass(slots=True)
class LLMRequest:
    model: str
    system: str
    messages: list[LLMMessage]
    temperature: float = 0.3
    max_tokens: int = 1024
    timeout_seconds: int = 30
    response_format: str | None = None  # "json" hint; providers can honor or ignore


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    usage: dict[str, int]
    latency_ms: int
    raw: dict | None = None


class LLMAdapter(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse:  # pragma: no cover - protocol
        ...
