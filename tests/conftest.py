"""Test configuration: isolate the DB, force the mock provider."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Force mock provider + test env BEFORE any app imports.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ["JUDGE_PROVIDER"] = ""  # Tests must use mock for judging too


@pytest.fixture(scope="session")
def _tmp_root():
    path = Path(tempfile.mkdtemp(prefix="ega_test_"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _isolated_settings(_tmp_root):
    """Point DB and reports at a throwaway dir and initialize schema."""
    db_path = _tmp_root / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["EVAL_REPORTS_DIR"] = str(_tmp_root / "reports")

    # Clear caches so the above env actually takes effect.
    from app.backend.core.config import get_settings
    from app.backend.llm.factory import reset_adapter_cache
    from app.backend.persistence.database import init_db, reset_engine_for_tests

    get_settings.cache_clear()
    reset_adapter_cache()
    reset_engine_for_tests()
    # Lifespan doesn't run under ASGITransport; create tables explicitly.
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(init_db())
    yield


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the session (required by some async fixtures)."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
