"""Interactive scenario-creation wizard for first-time operators.

Goal: compress the README pre-flight checklist into a single sub-minute
interactive flow so a new operator can go from `pip install` to a real
scenario row + scheduled delayed checks without copy-pasting six commands.

The wizard never makes network requests, never reads credentials, and
never logs in. It only creates database rows.
"""

from __future__ import annotations

import re
import secrets

import typer
from rich.console import Console
from sqlalchemy.orm import Session

from app.models import Scenario, ScenarioMetadata
from app.scheduler import schedule_delayed_check
from app.transitions import SCENARIO_TEMPLATE_LIBRARY

_DEFAULT_DELAYS: tuple[str, ...] = ("5m", "1h", "24h")
_PROBE_TAG = "SIL-PROBE"


def _generate_signature() -> str:
    return f"{_PROBE_TAG}-{secrets.token_hex(4)}"


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-")
    return s or "scenario"


def _ask_template(console: Console) -> str:
    keys = list(SCENARIO_TEMPLATE_LIBRARY)
    console.print("\n[bold]1. Pick a scenario template:[/bold]")
    for idx, key in enumerate(keys, start=1):
        tpl = SCENARIO_TEMPLATE_LIBRARY[key]
        console.print(f"  {idx}. [cyan]{key}[/cyan] — {tpl.title}")
    while True:
        choice = typer.prompt(
            f"Enter number (1-{len(keys)}) or key",
            default="1",
        ).strip()
        if choice in SCENARIO_TEMPLATE_LIBRARY:
            return choice
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(keys):
                return keys[n - 1]
        console.print("[yellow]invalid choice; try again.[/yellow]")


def _ask_required_text(prompt_text: str) -> str:
    while True:
        value = typer.prompt(prompt_text).strip()
        if value:
            return value


def _ask_yesno(prompt_text: str, *, default: bool = True) -> bool:
    return typer.confirm(prompt_text, default=default)


def run_wizard(session: Session, console: Console) -> Scenario:
    """Drive the wizard. Commits a Scenario + ScenarioMetadata +
    DelayedCheck rows, prints the next commands, and returns the
    created scenario."""

    console.print(
        "\n[bold]State Integrity Lab — first-scenario wizard[/bold]\n"
        "Each step asks one question. Press Ctrl-C to abort at any time.\n"
        "Reminder: SIL is for operators auditing their OWN accounts or an "
        "explicitly authorized Bug Bounty scope. Do not point it at services "
        "you have no permission to test.\n"
    )

    template_key = _ask_template(console)
    template = SCENARIO_TEMPLATE_LIBRARY[template_key]
    console.print(f"  → selected [green]{template.title}[/green]\n")

    target_service = _ask_required_text("2. Target service (short name, e.g. acme.example)")

    scope_source = _ask_required_text(
        "3. Where is your authorization documented? (BB program URL, sandbox "
        "tenant note, or QA charter line)"
    )

    name_hint = f"{_slug(target_service)}-{template_key}-{secrets.token_hex(2)}"
    scenario_name = typer.prompt(
        "4. Scenario short-name (used for the artifact directory slug)",
        default=name_hint,
    ).strip() or name_hint

    use_signature = _ask_yesno(
        "5. Generate a unique probe signature you can plant in test data?",
        default=True,
    )
    signature = _generate_signature() if use_signature else ""

    schedule_delays = _ask_yesno(
        "6. Schedule delayed re-observations at 5m / 1h / 24h?", default=True
    )

    # ---- write to DB ----
    scenario = Scenario(
        name=scenario_name,
        target_service=target_service,
        hypothesis=template.hypothesis,
        template=template.key,
        status="in_progress",
    )
    session.add(scenario)
    session.flush()

    metadata = ScenarioMetadata(
        scenario_id=scenario.id,
        scope_authorization=scope_source,
        test_data_used=(
            f"Probe signature: {signature}. Plant this string into test data on "
            "the operator's own account before running `before`."
            if signature
            else ""
        ),
        expected_behavior=template.hypothesis,
    )
    session.add(metadata)

    scheduled_ids: list[int] = []
    if schedule_delays:
        for delay in _DEFAULT_DELAYS:
            row = schedule_delayed_check(
                session,
                scenario.id,
                delay,
                note=f"wizard-scheduled {delay} re-observation",
            )
            scheduled_ids.append(row.id)

    session.flush()

    # ---- next-step prescription ----
    console.print("\n[bold green]Scenario created.[/bold green]")
    console.print(f"  id: {scenario.id}  name: {scenario.name}")
    console.print(f"  template: {template.key}")
    if signature:
        console.print(f"\n[bold]Probe signature:[/bold] [cyan]{signature}[/cyan]")
        console.print(
            "  Plant this string in your test data BEFORE capturing the `before` phase."
        )
    if scheduled_ids:
        console.print(
            f"\nScheduled delayed checks: ids={scheduled_ids} (5m / 1h / 24h)"
        )

    keyword_flag = f" --keyword {signature}" if signature else ""
    console.print("\n[bold]Next commands:[/bold]")
    console.print(f"  sil scenario show-template {template.key}    # re-read the playbook")
    console.print(
        f"  sil observe html --scenario {scenario.id} --phase before --file ./snapshot.html"
    )
    console.print(
        "  # ... perform the state transition manually, then capture `after` ..."
    )
    console.print(
        f"  sil observe html --scenario {scenario.id} --phase after  --file ./after.html"
    )
    console.print(
        f"  sil diff --before <before_obs_id> --after <after_obs_id>{keyword_flag}"
    )
    console.print(
        "  sil scheduler run-due           # later, when delayed checks become due"
    )
    console.print(
        f"  sil report generate --scenario {scenario.id}"
    )
    console.print(
        f"  sil scenario export   --scenario {scenario.id}   # pack for submission"
    )
    console.print("")

    return scenario
