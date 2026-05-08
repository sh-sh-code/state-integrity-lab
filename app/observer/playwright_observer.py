"""Playwright observer for State Integrity Lab.

Phase 2 design constraints (do not relax these):

- The observer **never** logs in. It only loads an existing
  `storage_state.json` provided by the operator. SIL must not store, prompt
  for, or capture credentials.
- The operator is responsible for ensuring the URL is in scope for the
  authorized test (their own account, sandbox tenant, or Bug Bounty scope).
- Each call captures one URL, screenshot + DOM, then closes the browser.
  No crawling, no concurrent pages, no rate-evading behavior.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import Observation, Scenario
from app.storage.artifacts import scenario_dir


def is_playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    return True


class PlaywrightUnavailable(RuntimeError):
    """Raised when Playwright is not installed."""


class StorageStateRequired(ValueError):
    """Raised when no storage_state path was provided."""


def capture_page(
    session: Session,
    scenario_id: int,
    phase: str,
    *,
    url: str,
    storage_state: Path,
    wait_for: str | None = None,
    mask_selectors: list[str] | None = None,
    note: str = "",
    label: str = "page",
    timeout_ms: int = 15000,
) -> tuple[Observation, Observation]:
    """Open `url` with the supplied storage_state, save screenshot + DOM.

    Returns a tuple `(screenshot_observation, html_observation)`.

    Both files are stored under `artifacts/scenario_<id>_<slug>/<phase>/`.
    """
    if not is_playwright_available():
        raise PlaywrightUnavailable(
            "Playwright is not installed. Install with `pip install state-integrity-lab[playwright]` "
            "and run `playwright install chromium`."
        )
    if storage_state is None:
        raise StorageStateRequired(
            "Playwright observer requires --storage-state. "
            "SIL must not perform logins; export an existing logged-in profile and pass it in."
        )
    storage_path = Path(storage_state)
    if not storage_path.exists():
        raise StorageStateRequired(f"storage_state file does not exist: {storage_path}")

    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise ValueError(f"Scenario id={scenario_id} not found.")
    target = scenario_dir(scenario.id, scenario.name, phase)

    from playwright.sync_api import sync_playwright

    screenshot_path = target / f"{_ts()}_{_slug(label)}.png"
    html_path = target / f"{_ts()}_{_slug(label)}.html"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=str(storage_path))
            try:
                page = context.new_page()
                page.set_default_timeout(timeout_ms)
                page.goto(url, wait_until="networkidle")
                if wait_for:
                    page.wait_for_selector(wait_for)
                _apply_masks(page, mask_selectors or [])
                page.screenshot(path=str(screenshot_path), full_page=True)
                html_path.write_text(page.content(), encoding="utf-8")
            finally:
                context.close()
        finally:
            browser.close()

    note_for_record = note or f"playwright capture of {url}"
    shot_obs = Observation(
        scenario_id=scenario.id,
        phase=phase,
        observer_type="screenshot",
        artifact_path=str(screenshot_path),
        note=note_for_record,
    )
    html_obs = Observation(
        scenario_id=scenario.id,
        phase=phase,
        observer_type="html",
        artifact_path=str(html_path),
        note=note_for_record,
    )
    session.add(shot_obs)
    session.add(html_obs)
    session.flush()
    return shot_obs, html_obs


def _apply_masks(page: Any, selectors: list[str]) -> None:
    """Visually black out elements before screenshot (used to hide PII like avatars)."""
    if not selectors:
        return
    css = "\n".join(f"{s} {{ background: #000 !important; color: #000 !important; }}" for s in selectors)
    page.add_style_tag(content=css)


def _ts() -> str:
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-") or "capture"
