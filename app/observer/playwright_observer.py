"""Playwright-backed observer (Phase 2 placeholder).

Phase 1 does NOT drive a browser automatically. Logging into third-party
services with stored credentials raises significant safety, ToS and scope
questions, so the automation hook is left as an explicit Phase 2 task.

This module simply detects whether Playwright is installed so the CLI can
print a helpful message.
"""

from __future__ import annotations


def is_playwright_available() -> bool:
    try:
        import playwright  # type: ignore  # noqa: F401
    except Exception:
        return False
    return True


def capture_page(*_args, **_kwargs) -> None:  # pragma: no cover - intentional stub.
    raise NotImplementedError(
        "Playwright-driven observation is reserved for Phase 2. "
        "Capture screenshots / HTML manually and pass them to the CLI."
    )
