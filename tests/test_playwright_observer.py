"""Playwright observer tests.

If `playwright` is not installed, the only assertion we can make is that the
observer raises `PlaywrightUnavailable`. We do not download browsers in CI;
real browser-driven tests are out of scope for the unit-test layer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db import session_scope
from app.models import Scenario
from app.observer.playwright_observer import (
    PlaywrightUnavailable,
    StorageStateRequired,
    capture_page,
    is_playwright_available,
)


def _make_scenario() -> int:
    with session_scope() as session:
        scenario = Scenario(name="pw_scn", target_service="example.com", hypothesis="x")
        session.add(scenario)
        session.flush()
        return scenario.id


def test_capture_page_requires_storage_state(tmp_path: Path) -> None:
    sid = _make_scenario()
    missing = tmp_path / "nope.json"
    with session_scope() as session:
        if not is_playwright_available():
            with pytest.raises(PlaywrightUnavailable):
                capture_page(
                    session,
                    sid,
                    "before",
                    url="https://example.com",
                    storage_state=missing,
                )
            return
        with pytest.raises(StorageStateRequired):
            capture_page(
                session,
                sid,
                "before",
                url="https://example.com",
                storage_state=missing,
            )
