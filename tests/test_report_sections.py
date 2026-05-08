"""Tests for the enhanced Bug Bounty / QA report sections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from app.cli import app
from app.db import session_scope
from app.models import (
    DiffResult,
    Observation,
    Scenario,
    ScenarioMetadata,
    Transition,
)
from app.reports import generate_markdown_report


def _setup_scenario(name: str, *, with_metadata: bool) -> int:
    base_ts = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
    with session_scope() as session:
        scenario = Scenario(
            name=name,
            target_service="example.com",
            hypothesis="deleted items must not appear post-transition",
            created_at=base_ts,
        )
        session.add(scenario)
        session.flush()
        sid = scenario.id

        before = Observation(
            scenario_id=sid, phase="before", observer_type="html",
            artifact_path=f"/tmp/{name}/before.html", note="initial",
            created_at=base_ts + timedelta(seconds=1),
        )
        after = Observation(
            scenario_id=sid, phase="after", observer_type="html",
            artifact_path=f"/tmp/{name}/after.html", note="post",
            created_at=base_ts + timedelta(seconds=3),
        )
        session.add_all([before, after])
        session.flush()

        transition = Transition(
            scenario_id=sid, transition_type="deleted_file",
            performed_by="human", note="manual delete",
            created_at=base_ts + timedelta(seconds=2),
        )
        session.add(transition)

        diff = DiffResult(
            scenario_id=sid,
            before_observation_id=before.id,
            after_observation_id=after.id,
            diff_type="text",
            summary="keyword still present",
            severity_hint="needs_review",
            created_at=base_ts + timedelta(seconds=4),
        )
        session.add(diff)

        if with_metadata:
            meta = ScenarioMetadata(
                scenario_id=sid,
                scope_authorization="Tested only against my own account on example.com.",
                test_data_used="One uploaded file with signature SIL-PROBE-XYZ.",
                expected_behavior="Deleted file must not appear in retrieval after 5m.",
                actual_behavior="File body returned 75 minutes after deletion.",
                security_impact="Stale knowledge available to anyone with retrieval access.",
                limitations="Tested on 1 region; could not check EU pop.",
                recommended_fix="Tombstone in retrieval index and purge CDN on delete.",
            )
            session.add(meta)
        session.flush()
        return sid


def _generate(scenario_id: int) -> str:
    with session_scope() as session:
        path = generate_markdown_report(session, scenario_id, redact_secrets=False)
    return Path(path).read_text(encoding="utf-8")


def test_report_contains_all_required_sections_with_metadata() -> None:
    sid = _setup_scenario("rpt_with_meta", with_metadata=True)
    text = _generate(sid)
    for heading in (
        "## Scope and Authorization",
        "## Test Data Used",
        "## Timeline",
        "## Expected vs Actual",
        "## Security Impact",
        "## Evidence",
        "## Limitations",
        "## Recommended Fix Direction",
    ):
        assert heading in text, f"missing heading {heading!r}"


def test_report_uses_placeholder_when_metadata_absent() -> None:
    sid = _setup_scenario("rpt_no_meta", with_metadata=False)
    text = _generate(sid)
    assert "## Scope and Authorization" in text
    assert "to be filled in by the operator" in text


def test_timeline_orders_events_chronologically() -> None:
    sid = _setup_scenario("rpt_timeline", with_metadata=False)
    text = _generate(sid)
    timeline_idx = text.index("## Timeline")
    next_section_idx = text.index("##", timeline_idx + 1)
    block = text[timeline_idx:next_section_idx]
    timestamps = [line for line in block.splitlines() if line.startswith("- 20")]
    assert len(timestamps) >= 4  # 2 obs + 1 transition + 1 diff
    assert timestamps == sorted(timestamps)


def test_evidence_section_lists_artifact_paths() -> None:
    sid = _setup_scenario("rpt_evidence", with_metadata=True)
    text = _generate(sid)
    assert "## Evidence" in text
    assert "before.html" in text
    assert "after.html" in text


def test_cli_annotate_then_show_metadata_round_trip() -> None:
    sid = _setup_scenario("rpt_annotate", with_metadata=False)
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "scenario",
            "annotate",
            "--scenario",
            str(sid),
            "--scope",
            "own account",
            "--expected",
            "no residual",
            "--actual",
            "residual seen",
        ],
    )
    assert r.exit_code == 0, r.stdout

    s = runner.invoke(app, ["scenario", "show-metadata", "--scenario", str(sid)])
    assert s.exit_code == 0, s.stdout
    assert "scope_authorization" in s.stdout
    assert "own account" in s.stdout
    assert "no residual" in s.stdout


def test_cli_annotate_requires_at_least_one_field() -> None:
    sid = _setup_scenario("rpt_annotate_empty", with_metadata=False)
    runner = CliRunner()
    r = runner.invoke(app, ["scenario", "annotate", "--scenario", str(sid)])
    assert r.exit_code != 0


def test_redact_masks_email_in_metadata() -> None:
    sid = _setup_scenario("rpt_redact", with_metadata=True)
    with session_scope() as session:
        scenario = session.get(Scenario, sid)
        assert scenario is not None
        scenario.metadata_row.scope_authorization = (
            "Tested under my own account alice@example.com only."
        )
    with session_scope() as session:
        path = generate_markdown_report(session, sid, redact_secrets=True)
    text = Path(path).read_text(encoding="utf-8")
    assert "alice@example.com" not in text
    assert "[REDACTED_EMAIL]" in text
