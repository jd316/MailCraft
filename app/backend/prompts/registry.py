"""Prompt registry — loads versioned prompt templates from disk, caches them.

Prompts are deliberately stored as Markdown so they are diff-friendly and
easy to review. The registry is the single source of truth for which
strategies exist and where their text lives.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.backend.core.config import ROOT_DIR
from app.backend.core.errors import NotFound

PROMPTS_DIR = ROOT_DIR / "prompts"


@dataclass(slots=True, frozen=True)
class PromptTemplate:
    version: str
    strategy: str
    system_text: str


_REGISTRY: dict[str, tuple[str, Path]] = {
    # version -> (strategy, file_path)
    "baseline_v1": ("baseline", PROMPTS_DIR / "base" / "baseline_v1.md"),
    "advanced_v1": ("advanced_role_fewshot_cot", PROMPTS_DIR / "few_shot" / "advanced_v1.md"),
}


@lru_cache(maxsize=16)
def load_prompt(version: str) -> PromptTemplate:
    if version not in _REGISTRY:
        raise NotFound(f"Unknown prompt_version: {version}")
    strategy, path = _REGISTRY[version]
    if not path.exists():
        raise NotFound(f"Prompt template file missing: {path}")
    return PromptTemplate(version=version, strategy=strategy, system_text=path.read_text())


def list_versions() -> list[str]:
    return sorted(_REGISTRY.keys())
