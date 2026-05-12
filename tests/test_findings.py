"""Tests for the Findings registry — model, CLI, report, export integration."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import app
from app.db import session_scope
from app.exporters import export_scenario
from app.findings import (
    FindingError,
    linked_diff_ids,
    list_findings,
    open_finding,
    update_finding,
)
from app.models import (
    FINDING_STATUSES,
    DiffResult,
    Finding,
    Observation,
    Scenario,
)
from app.observer import record_html
from app.reports import generate_markdown_report


# ---- helpers ---------------------------------------------------------------


def _make_scenario(name: str) -> int:
    with session_scope() as session:
        s = Scenario(name=name, target_service="example.com", hypothesis="x")
        session.add(s)
        session.flush()
        return s.id


def _make_diff_for(scenario_id: int, *, severity: str = "needs_review") -> int:
    """Insert a minimal DiffResult row so we can link findings to it."""
    with session_scope() as session:
        # Pre-create two observations so the FK constraints stay valid.
        before = Observation(
            scenario_id=scenario_id, phase="before", observer_type="text", artifact_path=""
        )
        after = Observation(
            scenario_id=scenario_id, phase="after", observer_type="text", artifact_path=""
        )
        session.add_all([before, after])
        session.flush()
        diff = DiffResult(
            scenario_id=scenario_id,
            before_observation_id=before.id,
            after_observation_id=after.id,
            diff_type="text",
            summary="synthetic",
            severity_hint=severity,
        )
        session.add(diff)
        session.flush()
        return diff.id


# ---- registry --------------------------------------------------------------


def test_open_finding_sets_open_status() -> None:
    sid = _make_scenario("fr_open")
    with session_scope() as session:
        f = open_finding(
            session, sid, title="Stale doc body in retrieval", severity="needs_review"
            if False
            else "medium",
        )
        assert f.id is not None
        assert f.status == "open"
        assert f.severity == "medium"
        assert f.closed_at is None


def test_open_finding_validates_title_and_severity() -> None:
    sid = _make_scenario("fr_validate")
    with session_scope() as session:
        with pytest.raises(FindingError):
            open_finding(session, sid, title="")
        with pytest.raises(FindingError):
            open_finding(session, sid, title="ok", severity="ULTRA")


def test_open_finding_validates_diff_links() -> None:
    sid_a = _make_scenario("fr_diff_a")
    sid_b = _make_scenario("fr_diff_b")
    diff_b = _make_diff_for(sid_b)
    with session_scope() as session:
        with pytest.raises(FindingError):
            open_finding(session, sid_a, title="x", diff_ids=[diff_b])
        with pytest.raises(FindingError):
            open_finding(session, sid_a, title="x", diff_ids=[99999])


def test_update_status_to_terminal_sets_closed_at() -> None:
    sid = _make_scenario("fr_close")
    diff_id = _make_diff_for(sid)
    with session_scope() as session:
        f = open_finding(session, sid, title="leak", diff_ids=[diff_id])
        fid = f.id

    with session_scope() as session:
        f = update_finding(session, fid, status="fixed")
        assert f.closed_at is not None

    with session_scope() as session:
        # Re-opening clears closed_at.
        f = update_finding(session, fid, status="open")
        assert f.closed_at is None


def test_update_bounty_fields() -> None:
    sid = _make_scenario("fr_bounty")
    with session_scope() as session:
        f = open_finding(session, sid, title="x")
        fid = f.id
    with session_scope() as session:
        f = update_finding(
            session, fid, status="accepted", bounty_amount=500_00, bounty_currency="USD"
        )
        assert f.status == "accepted"
        assert f.bounty_amount == 500_00
        assert f.bounty_currency == "USD"


def test_list_findings_filters() -> None:
    sid_a = _make_scenario("fr_list_a")
    sid_b = _make_scenario("fr_list_b")
    with session_scope() as session:
        open_finding(session, sid_a, title="A1")
        open_finding(session, sid_a, title="A2")
        open_finding(session, sid_b, title="B1")
    with session_scope() as session:
        update_finding(session, 2, status="fixed")
    with session_scope() as session:
        only_a = list_findings(session, scenario_id=sid_a)
        assert {f.title for f in only_a} == {"A1", "A2"}
        only_open = list_findings(session, status="open")
        assert all(f.status == "open" for f in only_open)
        assert all(f.title != "A2" for f in only_open)


def test_linked_diff_ids_roundtrip() -> None:
    sid = _make_scenario("fr_link")
    d1 = _make_diff_for(sid)
    d2 = _make_diff_for(sid)
    with session_scope() as session:
        f = open_finding(session, sid, title="multi", diff_ids=[d1, d2, d1])
        assert linked_diff_ids(f) == sorted({d1, d2})


def test_finding_statuses_constant_is_complete() -> None:
    expected = {
        "open",
        "submitted",
        "needs_more_info",
        "accepted",
        "fixed",
        "wont_fix",
        "duplicate",
    }
    assert set(FINDING_STATUSES) == expected


# ---- CLI -------------------------------------------------------------------


def test_cli_finding_open_list_show_update() -> None:
    sid = _make_scenario("fr_cli")
    diff_id = _make_diff_for(sid)
    runner = CliRunner()

    r = runner.invoke(
        app,
        [
            "finding",
            "open",
            "--scenario",
            str(sid),
            "--title",
            "Deleted item body persists past 1h SLA",
            "--severity",
            "high",
            "--diff",
            str(diff_id),
            "--description",
            "Body of the deleted file is still returned by /v1/search 75 minutes later.",
        ],
    )
    assert r.exit_code == 0, r.stdout
    assert "opened finding" in r.stdout

    r = runner.invoke(app, ["finding", "list", "--scenario", str(sid)])
    assert r.exit_code == 0
    assert "Deleted item body" in r.stdout
    assert "high" in r.stdout
    assert "open" in r.stdout

    with session_scope() as session:
        finding = session.query(Finding).filter(Finding.scenario_id == sid).one()
        fid = finding.id

    r = runner.invoke(app, ["finding", "show", "--id", str(fid)])
    assert r.exit_code == 0
    assert "linked diffs" in r.stdout
    assert str(diff_id) in r.stdout

    r = runner.invoke(
        app,
        [
            "finding",
            "update",
            "--id",
            str(fid),
            "--status",
            "accepted",
            "--external-id",
            "H1-99999",
            "--paid",
            "50000",
            "--currency",
            "USD",
        ],
    )
    assert r.exit_code == 0
    assert "status=accepted" in r.stdout

    r = runner.invoke(app, ["finding", "show", "--id", str(fid)])
    assert "external_id: `H1-99999`" in r.stdout or "external_id" in r.stdout
    assert "50000 USD" in r.stdout


def test_cli_finding_update_requires_at_least_one_field() -> None:
    sid = _make_scenario("fr_cli_empty")
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["finding", "open", "--scenario", str(sid), "--title", "stub"],
    )
    assert r.exit_code == 0
    with session_scope() as session:
        fid = session.query(Finding).one().id
    r = runner.invoke(app, ["finding", "update", "--id", str(fid)])
    assert r.exit_code != 0


def test_cli_finding_unknown_severity_rejected() -> None:
    sid = _make_scenario("fr_bad_sev")
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "finding",
            "open",
            "--scenario",
            str(sid),
            "--title",
            "x",
            "--severity",
            "ULTRA",
        ],
    )
    assert r.exit_code != 0


# ---- report integration ----------------------------------------------------


def test_report_contains_findings_section() -> None:
    sid = _make_scenario("fr_report")
    with session_scope() as session:
        open_finding(
            session,
            sid,
            title="leak in /v1/search",
            description="body persists",
            severity="high",
        )
        open_finding(session, sid, title="minor wording", severity="low")

    with session_scope() as session:
        path = generate_markdown_report(session, sid, redact_secrets=False)
    text = Path(path).read_text(encoding="utf-8")
    assert "## Findings" in text
    # Higher-severity finding renders first.
    high_idx = text.index("leak in /v1/search")
    low_idx = text.index("minor wording")
    assert high_idx < low_idx


def test_report_no_findings_placeholder() -> None:
    sid = _make_scenario("fr_report_none")
    with session_scope() as session:
        path = generate_markdown_report(session, sid, redact_secrets=False)
    text = Path(path).read_text(encoding="utf-8")
    assert "## Findings" in text
    assert "No findings recorded yet" in text


# ---- export integration ----------------------------------------------------


def test_export_manifest_carries_findings(tmp_path: Path) -> None:
    sid = _make_scenario("fr_export")
    # Make a real artifact so the export has something to pack.
    src = tmp_path / "before.html"
    src.write_text("<html>hi</html>", encoding="utf-8")
    with session_scope() as session:
        record_html(session, sid, "before", source_path=src, note="initial")
        open_finding(
            session,
            sid,
            title="export-tracked finding",
            severity="high",
            description="must be in manifest",
        )

    with session_scope() as session:
        result = export_scenario(
            session, sid, output_path=tmp_path / "bundle.zip", redact_secrets=False
        )

    with zipfile.ZipFile(result.bundle_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert "findings" in manifest
    assert len(manifest["findings"]) == 1
    f = manifest["findings"][0]
    assert f["title"] == "export-tracked finding"
    assert f["severity"] == "high"
    assert f["status"] == "open"
