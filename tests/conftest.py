"""Test fixtures.

Each test gets a fresh SQLite DB and an isolated artifacts/reports tree,
so tests never touch the user's real data.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import app.config as config_module
import app.db as db_module
from app.db import init_db


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "sil.sqlite3"
    artifacts = tmp_path / "artifacts"
    reports = tmp_path / "reports"
    monkeypatch.setenv("SIL_DB_PATH", str(db_path))
    monkeypatch.setenv("SIL_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SIL_REPORTS_DIR", str(reports))
    monkeypatch.setenv("SIL_REDACT_BY_DEFAULT", "true")

    # Reset cached engine / sessionmaker between tests.
    db_module._engine = None  # type: ignore[attr-defined]
    db_module._SessionLocal = None  # type: ignore[attr-defined]

    settings = config_module.Settings.load()
    init_db(settings)
    yield settings

    db_module._engine = None  # type: ignore[attr-defined]
    db_module._SessionLocal = None  # type: ignore[attr-defined]
    for var in ("SIL_DB_PATH", "SIL_ARTIFACTS_DIR", "SIL_REPORTS_DIR", "SIL_REDACT_BY_DEFAULT"):
        os.environ.pop(var, None)
