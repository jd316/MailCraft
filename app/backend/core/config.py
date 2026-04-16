"""Application configuration, loaded once from environment.

All runtime configuration flows through the `Settings` instance. Environment
variables override defaults. Secrets (API keys) are never logged — see
`app.backend.core.logging` for redaction rules.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    # Binds to all interfaces by default because the primary deployment
    # target is a container (Docker/k8s) where the network boundary is
    # enforced by the orchestrator, not by localhost binding. For local
    # non-containerized runs, set APP_HOST=127.0.0.1.
    app_host: str = "0.0.0.0"  # nosec B104
    app_port: int = 8000
    log_level: str = "INFO"
    cors_allow_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    llm_provider: Literal["bedrock", "gemini", "mock"] = "bedrock"
    google_api_key: str | None = None
    aws_region: str = "us-east-1"

    model_primary: str = "mistral.mistral-large-3-675b-instruct"
    model_secondary: str = "mistral.mistral-small-2402-v1:0"
    model_judge: str = "mistral.mistral-large-3-675b-instruct"
    # Optional: use a different provider for the LLM judge (e.g. "gemini").
    # When set, eval metrics use this provider for judge calls instead of llm_provider.
    judge_provider: Literal["bedrock", "gemini", ""] = ""
    # Optional backup model; when set, generation retries once against it on
    # upstream failure. Docs/03 §9 "provider failure → fallback to backup model".
    model_fallback: str | None = None

    gen_temperature: float = 0.3
    gen_max_tokens: int = 1024
    gen_timeout_seconds: int = 30

    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    rate_limit_generate: str = "30/minute"
    rate_limit_eval: str = "3/minute"

    eval_reports_dir: Path = Field(default=ROOT_DIR / "eval" / "reports")
    eval_scenarios_dir: Path = Field(default=ROOT_DIR / "eval" / "scenarios")
    eval_references_dir: Path = Field(default=ROOT_DIR / "eval" / "references")
    # Bounded concurrency for evaluation fan-out — respects provider rate limits
    # while still parallelizing the 20 scenario×config scoring calls.
    eval_concurrency: int = 4

    max_intent_chars: int = 400
    max_fact_chars: int = 400
    max_facts: int = 15
    max_revision_chars: int = 500
    # Starlette enforces this at the middleware layer; protects against
    # oversized-body abuse before deserialization.
    max_body_bytes: int = 32_768

    # Security headers
    enable_security_headers: bool = True

    # Retention (docs/08 §5 "retention must be configurable"). 0 disables
    # automatic cleanup. The `clean-drafts` CLI command honors this.
    draft_retention_days: int = 0

    @field_validator("cors_allow_origins")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return ",".join(p.strip() for p in v.split(",") if p.strip())

    @property
    def cors_origins_list(self) -> list[str]:
        return [p for p in self.cors_allow_origins.split(",") if p]

    @property
    def effective_provider(self) -> Literal["bedrock", "gemini", "mock"]:
        """Resolve the active LLM provider.

        - `LLM_PROVIDER=mock` → mock (explicit; used by tests).
        - `LLM_PROVIDER=bedrock` → bedrock (uses AWS credentials from env/profile).
        - `LLM_PROVIDER=gemini` + key present → gemini.
        - `LLM_PROVIDER=gemini` + key missing + `APP_ENV=test` → mock.
        """
        if self.llm_provider == "mock":
            return "mock"
        if self.llm_provider == "bedrock":
            return "bedrock"
        if self.llm_provider == "gemini":
            if self.google_api_key:
                return "gemini"
            if self.app_env == "test":
                return "mock"
            raise RuntimeError(
                "GOOGLE_API_KEY is not set for the gemini provider.\n\n"
                "  Set GOOGLE_API_KEY=AIza... in your .env file."
            )
        return self.llm_provider  # type: ignore[return-value]

    def validate_for_runtime(self) -> None:
        """Raise if the current configuration is unsafe for the selected env.

        Called at app startup so misconfiguration fails fast.
        """
        # effective_provider already raises if key is missing outside test.
        # Additional production guards:
        if self.app_env == "production" and self.cors_allow_origins in {"", "*"}:
            raise RuntimeError(
                "APP_ENV=production requires an explicit CORS_ALLOW_ORIGINS list."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
