from __future__ import annotations

import json
from pathlib import Path

from app.diff import (
    detect_persistence,
    diff_json,
    diff_json_files,
    diff_screenshots,
    diff_text,
)


def test_diff_text_reports_added_and_removed_lines() -> None:
    before = "alpha\nbeta\ngamma\n"
    after = "alpha\ndelta\ngamma\n"
    out = diff_text(before, after)
    assert "-beta" in out
    assert "+delta" in out


def test_detect_persistence_flags_declared_keyword() -> None:
    before = "Search for foo: 3 results"
    after = "Search for foo: 1 result still mentions foo"
    findings = detect_persistence(before, after, keywords=["foo"])
    rules = {f.rule for f in findings}
    assert "declared_keyword_persisted" in rules


def test_detect_persistence_flags_internal_identifiers() -> None:
    before = "Welcome"
    after = (
        "Error 500: org_abc123def at "
        "/var/log/app/trace.log uuid=11111111-2222-3333-4444-555555555555"
    )
    findings = detect_persistence(before, after, keywords=[])
    rules = {f.rule for f in findings}
    assert "internal_identifier_visible" in rules
    severities = {f.severity_hint for f in findings}
    # uuid / org_id / abs path => medium; no stack trace here.
    assert "medium" in severities


def test_detect_persistence_flags_stack_trace_high() -> None:
    findings = detect_persistence(
        "ok",
        'Traceback (most recent call last):\n  File "x.py"',
        keywords=[],
    )
    assert any(f.severity_hint == "high" for f in findings)


def test_detect_persistence_returns_no_finding_for_clean_after() -> None:
    findings = detect_persistence(
        "before content with foo",
        "after content without the bad keyword",
        keywords=["foo"],
    )
    assert findings == []


def test_diff_json_detects_added_removed_changed() -> None:
    before = {"a": 1, "b": {"c": 2}, "d": [1, 2, 3]}
    after = {"a": 1, "b": {"c": 5}, "d": [1, 2], "e": "new"}
    diff = diff_json(before, after)
    assert not diff.is_empty
    paths_changed = {p for p, _, _ in diff.changed}
    paths_removed = {p for p, _ in diff.removed}
    paths_added = {p for p, _ in diff.added}
    assert "b.c" in paths_changed
    assert "d[2]" in paths_removed
    assert "e" in paths_added


def test_diff_json_files_round_trip(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"x": 1}))
    b.write_text(json.dumps({"x": 2}))
    diff = diff_json_files(a, b)
    assert not diff.is_empty
    assert diff.changed == [("x", 1, 2)]


def test_diff_screenshots_byte_compare(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"PNG-FAKE-DATA-AAA")
    b.write_bytes(b"PNG-FAKE-DATA-AAA")
    same = diff_screenshots(a, b)
    assert same.same_bytes is True

    b.write_bytes(b"PNG-FAKE-DATA-DIFFERENT")
    diff = diff_screenshots(a, b)
    assert diff.same_bytes is False
    assert diff.before_size != diff.after_size
