"""Tests for the scenario playbook surface (templates + CLI)."""

from __future__ import annotations

from typer.testing import CliRunner

from app.cli import app
from app.transitions import SCENARIO_TEMPLATE_LIBRARY, get_template


REQUIRED_PLAYBOOK_KEYS = (
    "connector_revoke_persistence",
    "project_knowledge_deletion",
    "team_permission_downgrade",
    "api_key_rotation_persistence",
    "export_after_deletion",
    "delayed_cache_inconsistency",
)


def test_all_required_playbooks_exist() -> None:
    for key in REQUIRED_PLAYBOOK_KEYS:
        assert key in SCENARIO_TEMPLATE_LIBRARY, f"missing playbook: {key}"


def test_each_playbook_has_full_fields() -> None:
    for key in REQUIRED_PLAYBOOK_KEYS:
        tpl = SCENARIO_TEMPLATE_LIBRARY[key]
        assert tpl.hypothesis
        assert tpl.suggested_observations
        assert tpl.persistence_keywords
        assert tpl.prerequisites, f"{key} is missing prerequisites"
        assert tpl.reportable_conditions, f"{key} is missing reportable conditions"
        assert tpl.false_positive_traps, f"{key} is missing false-positive traps"
        assert tpl.prohibited_actions, f"{key} is missing prohibited actions"
        assert tpl.recommended_fix_direction, f"{key} is missing fix direction"


def test_show_lines_contains_all_section_headings() -> None:
    tpl = get_template("connector_revoke_persistence")
    assert tpl is not None
    text = "\n".join(tpl.show_lines())
    for heading in (
        "## Hypothesis",
        "## Prerequisites",
        "## Suggested observations",
        "## Persistence keywords",
        "## Reportable conditions",
        "## False-positive traps",
        "## Prohibited actions",
        "## Recommended fix direction",
    ):
        assert heading in text, f"missing heading {heading}"


def test_cli_list_templates_alias() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["scenario", "list-templates"])
    assert result.exit_code == 0, result.stdout
    # Rich truncates very long keys in the table; probe unique prefixes only.
    for prefix in (
        "connector_revoke",
        "project_knowledge",
        "team_permission",
        "api_key_rotation",
        "export_after",
        "delayed_cache",
    ):
        assert prefix in result.stdout, f"{prefix!r} missing from listing"


def test_cli_show_template_known() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["scenario", "show-template", "connector_revoke_persistence"])
    assert result.exit_code == 0, result.stdout
    assert "Hypothesis" in result.stdout
    assert "Prerequisites" in result.stdout
    assert "Reportable conditions" in result.stdout
    assert "Prohibited actions" in result.stdout


def test_cli_show_template_unknown_rejected() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["scenario", "show-template", "no_such_template"])
    assert result.exit_code != 0
