"""Tests for the `sil init --wizard` interactive flow."""

from __future__ import annotations

from typer.testing import CliRunner

from app.cli import app
from app.db import session_scope
from app.models import DelayedCheck, Scenario, ScenarioMetadata


def _answers(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_wizard_creates_scenario_metadata_and_schedules() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--wizard"],
        input=_answers(
            "2",                          # template choice: 2nd in list
            "acme.example",               # target service
            "https://hackerone.com/acme", # scope source (URL is fine)
            "",                           # accept default scenario name
            "y",                          # generate probe signature
            "y",                          # schedule delayed checks
        ),
    )
    assert result.exit_code == 0, result.stdout
    assert "Scenario created" in result.stdout
    assert "Probe signature" in result.stdout
    # Next-commands prescription is printed.
    assert "sil observe html" in result.stdout
    assert "sil diff" in result.stdout
    assert "sil report generate" in result.stdout
    assert "sil scenario export" in result.stdout

    with session_scope() as session:
        scenarios = session.query(Scenario).all()
        assert len(scenarios) == 1
        scenario = scenarios[0]
        assert scenario.target_service == "acme.example"
        assert scenario.template is not None
        assert scenario.status == "in_progress"

        # Metadata captures scope and the signature mention.
        meta = scenario.metadata_row
        assert meta is not None
        assert "hackerone.com/acme" in meta.scope_authorization
        assert "SIL-PROBE-" in meta.test_data_used

        # Three delayed checks scheduled.
        checks = (
            session.query(DelayedCheck)
            .filter(DelayedCheck.scenario_id == scenario.id)
            .all()
        )
        assert len(checks) == 3


def test_wizard_accepts_template_by_key() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--wizard"],
        input=_answers(
            "export_after_deletion",
            "demo.example",
            "private brief",
            "myname",
            "n",          # no signature
            "n",          # no schedule
        ),
    )
    assert result.exit_code == 0, result.stdout
    with session_scope() as session:
        scenario = session.query(Scenario).one()
        assert scenario.template == "export_after_deletion"
        assert scenario.name == "myname"
        meta = scenario.metadata_row
        assert meta is not None
        assert meta.test_data_used == ""
        checks = (
            session.query(DelayedCheck)
            .filter(DelayedCheck.scenario_id == scenario.id)
            .all()
        )
        assert checks == []


def test_wizard_rejects_invalid_template_then_accepts_valid() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--wizard"],
        input=_answers(
            "no-such-template",  # invalid
            "999",               # invalid number
            "1",                 # valid
            "demo.example",
            "BB scope: own account",
            "",
            "n",
            "n",
        ),
    )
    assert result.exit_code == 0, result.stdout
    assert "invalid choice" in result.stdout
    with session_scope() as session:
        scenarios = session.query(Scenario).all()
        assert len(scenarios) == 1


def test_wizard_empty_required_fields_reprompt() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--wizard"],
        input=_answers(
            "1",
            "",                  # empty target (reprompt)
            "acme",
            "",                  # empty scope (reprompt)
            "BB-program-url",
            "",
            "n",
            "n",
        ),
    )
    assert result.exit_code == 0, result.stdout
    with session_scope() as session:
        scenario = session.query(Scenario).one()
        assert scenario.target_service == "acme"
        meta = scenario.metadata_row
        assert meta is not None
        assert meta.scope_authorization == "BB-program-url"


def test_init_without_wizard_skips_prompts() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stdout
    assert "initialized" in result.stdout
    assert "Scenario created" not in result.stdout
    # No scenarios created.
    with session_scope() as session:
        assert session.query(Scenario).count() == 0
        assert session.query(ScenarioMetadata).count() == 0
