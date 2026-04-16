"""Structured logging using structlog.

Emits JSON in production, pretty console logs in development. Redacts secrets
and well-known sensitive keys. The request-id processor binds per-request
context set by the middleware.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.backend.core.config import get_settings

_SENSITIVE_KEYS = {"anthropic_api_key", "api_key", "authorization", "password", "token", "secret"}


def _redact(_logger, _name, event_dict):
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def configure_logging() -> None:
    """Configure structlog + stdlib logging.

    Logs go to **stderr** (stdout is reserved for program output such as the
    CLI's JSON summary). Structlog delegates to the stdlib logger, which keeps
    pytest's capture machinery and `caplog` working.
    """
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    # Replace handlers so repeated configuration (tests, reload) doesn't duplicate.
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
    ]

    if settings.app_env == "development":
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None):
    return structlog.get_logger(name or "app")
