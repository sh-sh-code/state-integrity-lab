from __future__ import annotations

from app.diff.text_diff import (
    PersistenceFinding,
    detect_persistence,
    weighted_severity,
)


def _f(rule: str, severity: str, weight: float = 1.0) -> PersistenceFinding:
    return PersistenceFinding(
        rule=rule, keyword="x", severity_hint=severity, detail="d", weight=weight
    )


def test_weighted_severity_empty_is_info() -> None:
    sev, score = weighted_severity([])
    assert sev == "info"
    assert score == 0.0


def test_weighted_severity_high_when_stack_trace() -> None:
    findings = detect_persistence(
        "ok",
        'Traceback (most recent call last):\n  File "x.py"',
        keywords=[],
    )
    sev, score = weighted_severity(findings)
    assert sev == "high"
    assert score > 0


def test_weighted_severity_promoted_by_score_threshold() -> None:
    findings = [_f("internal_identifier_visible", "medium", weight=2.0)] * 3
    sev, score = weighted_severity(findings)
    assert score == 6.0
    assert sev == "needs_review"


def test_weighted_severity_low_for_single_unchanged_line() -> None:
    findings = [_f("line_unchanged_after_transition", "low", weight=1.0)]
    sev, score = weighted_severity(findings)
    assert sev == "low"
    assert score == 1.0


def test_keyword_persistence_yields_needs_review() -> None:
    findings = detect_persistence(
        "before content with foo",
        "after still mentions foo here",
        keywords=["foo"],
    )
    sev, _ = weighted_severity(findings)
    assert sev == "needs_review"
