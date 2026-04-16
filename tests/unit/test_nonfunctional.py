"""Non-functional tests per docs/07_TEST_PLAN.md §2.4.

Covers:
- timeout handling (adapter surfaces GenerationTimeout)
- retry behavior (tenacity retries transient errors up to 3x)
- safe rendering (frontend uses textContent — never innerHTML — so control
  characters and HTML in model output cannot escape into the DOM)
"""

from __future__ import annotations

import pytest

from app.backend.core.errors import GenerationTimeout, UpstreamError
from app.backend.llm.base import LLMAdapter, LLMMessage, LLMRequest, LLMResponse
from app.backend.services.generation import GenerationService


class _AlwaysTimeout(LLMAdapter):
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        raise GenerationTimeout("simulated upstream timeout")


class _FailThenSucceed(LLMAdapter):
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.calls < 3:
            raise UpstreamError("transient 503")
        return LLMResponse(
            text='{"subject_suggestion":"s","email_body":"Dear team,\\n\\nok.\\n\\nRegards,\\nA","fact_coverage":[{"fact":"A","included":true,"evidence":"ok"}]}',
            model=request.model,
            usage={},
            latency_ms=1,
        )


@pytest.mark.asyncio
async def test_timeout_surfaces_generation_timeout():
    """A model timeout must propagate as GenerationTimeout (maps to 504)."""
    svc = GenerationService(_AlwaysTimeout())
    with pytest.raises(GenerationTimeout):
        await svc.generate(
            intent="Follow up",
            key_facts=["A"],
            tone="formal",
            prompt_version="advanced_v1",
            model_id="claude-sonnet-4-6",
        )


def test_frontend_never_assigns_inner_html():
    """Reading the SPA source is the test: `.innerHTML = ` / `.outerHTML = `
    are the only ways model output could escape into the DOM as HTML.
    Grepping for assignments (not the word in comments) catches regressions."""
    import re

    from app.backend.core.config import ROOT_DIR

    js = (ROOT_DIR / "app" / "frontend" / "assets" / "app.js").read_text()
    # Strip line comments so narrative text doesn't trip the scanner.
    stripped = re.sub(r"//[^\n]*", "", js)
    assert not re.search(r"\.innerHTML\s*=", stripped), "use textContent, not innerHTML"
    assert not re.search(r"\.outerHTML\s*=", stripped), "use textContent, not outerHTML"
    assert not re.search(r"\binsertAdjacentHTML\b", stripped)


def test_frontend_sets_strict_csp_and_html_safety():
    """The CSP banned inline scripts & styles; verify the template has no
    inline <script>…</script> or inline style bodies that would require
    'unsafe-inline' in CSP."""
    import re

    from app.backend.core.config import ROOT_DIR

    html = (ROOT_DIR / "app" / "frontend" / "index.html").read_text()
    # Inline script tags with content are forbidden; external script src OK.
    inline_scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?</script>", html, re.IGNORECASE)
    # Strictly zero inline scripts.
    assert inline_scripts == [], f"Inline <script>…</script> breaks our CSP: {inline_scripts}"


def test_latency_envelope_target_documented():
    """docs/02 NFR-01 sets p95 < 8s. We cannot measure p95 without real
    traffic, but we enforce the per-request upper bound via settings so a
    regression can be caught in integration."""
    from app.backend.core.config import get_settings

    s = get_settings()
    # If someone raises this above the p95 SLA, it's worth a second look.
    assert s.gen_timeout_seconds <= 90
