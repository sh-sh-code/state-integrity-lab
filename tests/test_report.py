from __future__ import annotations

from pathlib import Path

from app.db import session_scope
from app.models import DiffResult, Observation, Scenario, Transition
from app.observer import record_html, record_manual
from app.reports import generate_markdown_report, redact
from app.scheduler import schedule_delayed_check


def _seed_scenario() -> int:
    with session_scope() as session:
        scenario = Scenario(
            name="example_scn",
            target_service="example.com",
            hypothesis="deleted content should disappear from all surfaces",
            template="project_knowledge_deletion",
            status="in_progress",
        )
        session.add(scenario)
        session.flush()
        return scenario.id


def test_redact_masks_common_secrets() -> None:
    text = (
        "Contact alice@example.com, token=sk_live_abcdef123456, "
        "id=11111111-2222-3333-4444-555555555555, ip=10.0.0.1"
    )
    masked = redact(text)
    assert "alice@example.com" not in masked
    assert "sk_live_abcdef123456" not in masked
    assert "11111111-2222-3333-4444-555555555555" not in masked
    assert "10.0.0.1" not in masked
    assert "[REDACTED_EMAIL]" in masked
    assert "[REDACTED_TOKEN]" in masked
    assert "[REDACTED_UUID]" in masked
    assert "[REDACTED_IP]" in masked


def test_generate_markdown_report_writes_expected_sections() -> None:
    sid = _seed_scenario()

    with session_scope() as session:
        before = record_manual(session, sid, "before", "captured 3 hits before")
        after = record_html(
            session,
            sid,
            "after",
            content="<html>after</html>",
            note="captured after deletion",
        )
        session.add(
            Transition(
                scenario_id=sid,
                transition_type="deleted_file",
                performed_by="human",
                note="deleted /docs/test.md",
            )
        )
        session.add(
            DiffResult(
                scenario_id=sid,
                before_observation_id=before.id,
                after_observation_id=after.id,
                diff_type="text",
                summary="-beta\n+gamma",
                severity_hint="low",
            )
        )
        schedule_delayed_check(session, sid, "1h", note="re-check later")

    with session_scope() as session:
        path = generate_markdown_report(session, sid)

    assert isinstance(path, Path)
    assert path.exists()
    content = path.read_text(encoding="utf-8")

    assert "State Integrity Lab Report" in content
    assert "example_scn" in content
    assert "Scope & Safety Statement" in content
    assert "## Observations" in content
    assert "## Transitions" in content
    assert "## Diff results" in content
    assert "## Delayed checks" in content
    assert "deleted_file" in content
    assert "re-check later" in content


def test_report_redacts_secrets_in_notes() -> None:
    sid = _seed_scenario()
    with session_scope() as session:
        record_manual(
            session,
            sid,
            "before",
            "Reach me at op@example.com — token sk_live_ABCDEFG12345",
        )

    with session_scope() as session:
        path = generate_markdown_report(session, sid)
    content = path.read_text(encoding="utf-8")
    assert "op@example.com" not in content
    assert "sk_live_ABCDEFG12345" not in content
    assert "[REDACTED_EMAIL]" in content
    assert "[REDACTED_TOKEN]" in content


def test_observation_artifact_lives_under_artifacts_dir() -> None:
    sid = _seed_scenario()
    with session_scope() as session:
        obs = record_manual(session, sid, "before", "manual note")
        assert obs.artifact_path is not None
        assert Path(obs.artifact_path).exists()
