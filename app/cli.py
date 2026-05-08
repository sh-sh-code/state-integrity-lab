"""Typer CLI for State Integrity Lab.

Usage:

    sil init
    sil scenario create --name <slug> --target-service <name> [--template ...]
    sil scenario list
    sil observe manual --scenario <id> --phase <before|after|delayed_after> --note "..."
    sil observe json   --scenario <id> --phase ... --file payload.json
    sil observe html   --scenario <id> --phase ... --file page.html
    sil observe screenshot --scenario <id> --phase ... --file shot.png
    sil observe api    --scenario <id> --phase ... --file response.json --endpoint /v1/x --status 200
    sil transition mark --scenario <id> --type revoked_oauth [--note "..."]
    sil transition list
    sil diff --before <obs_id> --after <obs_id> [--keyword foo --keyword bar]
    sil schedule --scenario <id> --in 5m [--in 1h --in 24h]
    sil report generate --scenario <id> [--no-redact]
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.config import get_settings
from app.db import init_db, session_scope
from app.diff import (
    detect_persistence,
    diff_bundles,
    diff_json_files,
    diff_screenshots,
    diff_text,
    weighted_severity,
)
from app.models import (
    OBSERVATION_PHASES,
    SCENARIO_STATUSES,
    DiffResult,
    Observation,
    Scenario,
    Transition,
)
from app.observer import (
    PlaywrightUnavailable,
    StorageStateRequired,
    capture_page,
    fetch_api_template,
    list_api_templates,
    record_api_response,
    record_html,
    record_json,
    record_manual,
    record_screenshot,
)
from app.reports import generate_markdown_report
from app.scheduler import (
    DEFAULT_DELAYS,
    list_due,
    mark_done,
    render_text,
    schedule_delayed_check,
)
from app.transitions import (
    KNOWN_TRANSITIONS,
    SCENARIO_TEMPLATE_LIBRARY,
    get_template,
    get_transition_spec,
)

app = typer.Typer(
    add_completion=False,
    help=(
        "State Integrity Lab — defensive QA / audit tool for verifying state-"
        "transition integrity in AI / SaaS services. Use only on your own "
        "accounts and within authorized Bug Bounty / audit scope."
    ),
)
scenario_app = typer.Typer(help="Manage verification scenarios.")
observe_app = typer.Typer(help="Record before / after / delayed_after observations.")
transition_app = typer.Typer(help="Mark state transitions performed by a human.")
report_app = typer.Typer(help="Generate Markdown reports.")
diff_app = typer.Typer(help="Diff bundles, etc.")
scheduler_app = typer.Typer(help="Inspect and execute delayed-check prompts.")

app.add_typer(scenario_app, name="scenario")
app.add_typer(observe_app, name="observe")
app.add_typer(transition_app, name="transition")
app.add_typer(report_app, name="report")
app.add_typer(diff_app, name="bundle")
app.add_typer(scheduler_app, name="scheduler")

console = Console()


def _check_phase(phase: str) -> None:
    if phase not in OBSERVATION_PHASES:
        raise typer.BadParameter(
            f"phase must be one of {OBSERVATION_PHASES}, got {phase!r}"
        )


@app.command()
def init() -> None:
    """Create the SQLite DB and artifact / report directories."""
    settings = get_settings()
    settings.ensure_dirs()
    init_db(settings)
    console.print(f"[green]initialized[/green] db={settings.db_path}")
    console.print(f"           artifacts={settings.artifacts_dir}")
    console.print(f"           reports  ={settings.reports_dir}")


# ---------- scenario ----------


@scenario_app.command("create")
def scenario_create(
    name: str = typer.Option(..., "--name", help="Unique short name (slug-friendly)."),
    target_service: str = typer.Option(..., "--target-service"),
    hypothesis: str = typer.Option("", "--hypothesis"),
    template: str | None = typer.Option(
        None,
        "--template",
        help=f"Optional template key. Known: {', '.join(SCENARIO_TEMPLATE_LIBRARY)}.",
    ),
    status: str = typer.Option("draft", "--status"),
) -> None:
    """Create a new scenario row."""
    if status not in SCENARIO_STATUSES:
        raise typer.BadParameter(f"status must be one of {SCENARIO_STATUSES}")
    template_obj = get_template(template) if template else None
    if template and template_obj is None:
        raise typer.BadParameter(
            f"unknown template {template!r}. Known: {list(SCENARIO_TEMPLATE_LIBRARY)}"
        )
    if template_obj and not hypothesis:
        hypothesis = template_obj.hypothesis

    init_db()
    with session_scope() as session:
        scenario = Scenario(
            name=name,
            target_service=target_service,
            hypothesis=hypothesis,
            template=template_obj.key if template_obj else None,
            status=status,
        )
        session.add(scenario)
        session.flush()
        console.print(
            f"[green]created scenario[/green] id={scenario.id} name={scenario.name}"
        )
        if template_obj:
            console.print(f"  template: {template_obj.title}")
            console.print("  suggested observations:")
            for o in template_obj.suggested_observations:
                console.print(f"   - {o}")


@scenario_app.command("list")
def scenario_list() -> None:
    init_db()
    with session_scope() as session:
        rows = session.query(Scenario).order_by(Scenario.id).all()
        table = Table("id", "name", "service", "status", "template", "created_at")
        for s in rows:
            table.add_row(
                str(s.id),
                s.name,
                s.target_service,
                s.status,
                s.template or "—",
                s.created_at.isoformat(timespec="seconds"),
            )
        console.print(table)


@scenario_app.command("templates")
def scenario_templates() -> None:
    """List built-in scenario templates."""
    table = Table("key", "title", "hypothesis")
    for tpl in SCENARIO_TEMPLATE_LIBRARY.values():
        table.add_row(tpl.key, tpl.title, tpl.hypothesis)
    console.print(table)


# ---------- observe ----------


@observe_app.command("manual")
def observe_manual(
    scenario_id: int = typer.Option(..., "--scenario"),
    phase: str = typer.Option(..., "--phase"),
    note: str = typer.Option(..., "--note"),
    label: str = typer.Option("manual", "--label"),
) -> None:
    _check_phase(phase)
    init_db()
    with session_scope() as session:
        obs = record_manual(session, scenario_id, phase, note, label=label)
        console.print(f"[green]recorded manual observation[/green] id={obs.id}")
        console.print(f"  artifact: {obs.artifact_path}")


@observe_app.command("screenshot")
def observe_screenshot(
    scenario_id: int = typer.Option(..., "--scenario"),
    phase: str = typer.Option(..., "--phase"),
    file: Path = typer.Option(..., "--file", exists=True, dir_okay=False, readable=True),
    note: str = typer.Option("", "--note"),
    label: str | None = typer.Option(None, "--label"),
) -> None:
    _check_phase(phase)
    init_db()
    with session_scope() as session:
        obs = record_screenshot(session, scenario_id, phase, file, note=note, label=label)
        console.print(f"[green]recorded screenshot[/green] id={obs.id}")
        console.print(f"  artifact: {obs.artifact_path}")


@observe_app.command("html")
def observe_html(
    scenario_id: int = typer.Option(..., "--scenario"),
    phase: str = typer.Option(..., "--phase"),
    file: Path | None = typer.Option(
        None, "--file", exists=True, dir_okay=False, readable=True
    ),
    inline: str | None = typer.Option(None, "--inline", help="Raw HTML text."),
    note: str = typer.Option("", "--note"),
    label: str = typer.Option("snapshot", "--label"),
) -> None:
    _check_phase(phase)
    if file is None and inline is None:
        raise typer.BadParameter("provide --file or --inline")
    init_db()
    with session_scope() as session:
        obs = record_html(
            session,
            scenario_id,
            phase,
            content=inline,
            source_path=file,
            note=note,
            label=label,
        )
        console.print(f"[green]recorded html snapshot[/green] id={obs.id}")
        console.print(f"  artifact: {obs.artifact_path}")


@observe_app.command("json")
def observe_json(
    scenario_id: int = typer.Option(..., "--scenario"),
    phase: str = typer.Option(..., "--phase"),
    file: Path | None = typer.Option(
        None, "--file", exists=True, dir_okay=False, readable=True
    ),
    inline: str | None = typer.Option(None, "--inline", help="Raw JSON text."),
    note: str = typer.Option("", "--note"),
    label: str = typer.Option("payload", "--label"),
) -> None:
    _check_phase(phase)
    if file is None and inline is None:
        raise typer.BadParameter("provide --file or --inline")
    init_db()
    payload = None
    if inline is not None:
        try:
            payload = json.loads(inline)
        except Exception as exc:
            raise typer.BadParameter(f"--inline is not valid JSON: {exc}") from exc
    with session_scope() as session:
        obs = record_json(
            session,
            scenario_id,
            phase,
            payload=payload,
            source_path=file,
            note=note,
            label=label,
        )
        console.print(f"[green]recorded json observation[/green] id={obs.id}")
        console.print(f"  artifact: {obs.artifact_path}")


@observe_app.command("api")
def observe_api(
    scenario_id: int = typer.Option(..., "--scenario"),
    phase: str = typer.Option(..., "--phase"),
    file: Path = typer.Option(..., "--file", exists=True, dir_okay=False, readable=True),
    endpoint: str = typer.Option("", "--endpoint"),
    status: int | None = typer.Option(None, "--status"),
    note: str = typer.Option("", "--note"),
) -> None:
    _check_phase(phase)
    init_db()
    text = file.read_text(encoding="utf-8")
    with session_scope() as session:
        obs = record_api_response(
            session,
            scenario_id,
            phase,
            body_text=text,
            endpoint=endpoint,
            status_code=status,
            note=note,
        )
        console.print(f"[green]recorded api observation[/green] id={obs.id}")
        console.print(f"  artifact: {obs.artifact_path}")


# ---------- transition ----------


@transition_app.command("mark")
def transition_mark(
    scenario_id: int = typer.Option(..., "--scenario"),
    type: str = typer.Option(..., "--type", help=f"One of: {', '.join(KNOWN_TRANSITIONS)}"),
    performed_by: str = typer.Option("human", "--by"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Record that a state transition has been performed (by you)."""
    spec = get_transition_spec(type)
    if spec is None:
        console.print(
            f"[yellow]warning:[/yellow] {type!r} is not in the known list. "
            "Recording it anyway."
        )
    init_db()
    with session_scope() as session:
        if session.get(Scenario, scenario_id) is None:
            raise typer.BadParameter(f"scenario id={scenario_id} not found")
        t = Transition(
            scenario_id=scenario_id,
            transition_type=type,
            performed_by=performed_by,
            note=note,
        )
        session.add(t)
        session.flush()
        console.print(f"[green]recorded transition[/green] id={t.id} type={t.transition_type}")
        if spec:
            console.print("  typical follow-ups:")
            for f in spec.typical_followups:
                console.print(f"   - {f}")


@transition_app.command("list")
def transition_list() -> None:
    table = Table("name", "description")
    for spec in KNOWN_TRANSITIONS.values():
        table.add_row(spec.name, spec.description)
    console.print(table)


# ---------- diff ----------


@app.command("diff")
def diff_cmd(
    before: int = typer.Option(..., "--before", help="before observation id"),
    after: int = typer.Option(..., "--after", help="after observation id"),
    keyword: list[str] = typer.Option(
        [], "--keyword", "-k", help="Keyword that should NOT appear after the transition."
    ),
    save: bool = typer.Option(True, "--save/--no-save", help="Save a DiffResult row."),
) -> None:
    """Compare two observations and surface persistence findings."""
    init_db()
    with session_scope() as session:
        b = session.get(Observation, before)
        a = session.get(Observation, after)
        if b is None or a is None:
            raise typer.BadParameter("observation id not found")
        if b.scenario_id != a.scenario_id:
            raise typer.BadParameter("observations belong to different scenarios")
        if not b.artifact_path or not a.artifact_path:
            raise typer.BadParameter("observations are missing artifact paths")

        before_path = Path(b.artifact_path)
        after_path = Path(a.artifact_path)
        diff_type = b.observer_type
        summary_parts: list[str] = []
        severity = "info"

        if b.observer_type == "json" and a.observer_type == "json":
            jd = diff_json_files(before_path, after_path)
            summary_parts.append("== Structural JSON diff ==")
            summary_parts.append(jd.summary())
            if not jd.is_empty:
                severity = "low"
            diff_type = "json"
        elif b.observer_type == "screenshot" and a.observer_type == "screenshot":
            sd = diff_screenshots(before_path, after_path)
            summary_parts.append("== Screenshot diff ==")
            summary_parts.append(sd.summary())
            severity = sd.severity_hint
            diff_type = "screenshot"
        else:
            before_text = before_path.read_text(encoding="utf-8", errors="replace")
            after_text = after_path.read_text(encoding="utf-8", errors="replace")
            text_diff_str = diff_text(before_text, after_text)
            summary_parts.append("== Unified text diff ==")
            summary_parts.append(text_diff_str or "(no textual differences)")
            findings = detect_persistence(before_text, after_text, keywords=keyword)
            if findings:
                summary_parts.append("")
                summary_parts.append("== Persistence findings ==")
                for f in findings:
                    summary_parts.append(f.to_summary_line())
                severity, score = weighted_severity(findings)
                summary_parts.append("")
                summary_parts.append(
                    f"weighted score = {score:.2f} -> severity hint = {severity}"
                )
            diff_type = "text"

        summary = "\n".join(summary_parts)
        console.print(summary)

        if save:
            row = DiffResult(
                scenario_id=b.scenario_id,
                before_observation_id=b.id,
                after_observation_id=a.id,
                diff_type=diff_type,
                summary=summary,
                severity_hint=severity,
            )
            session.add(row)
            session.flush()
            console.print(f"\n[green]saved diff[/green] id={row.id} severity={severity}")


# ---------- schedule ----------


@app.command("schedule")
def schedule_cmd(
    scenario_id: int = typer.Option(..., "--scenario"),
    in_: list[str] = typer.Option(
        list(DEFAULT_DELAYS), "--in", help="Delay (e.g. 5m, 1h, 24h). Repeatable."
    ),
    note: str = typer.Option("", "--note"),
) -> None:
    """Register delayed re-observation tasks. (Phase 1 only writes rows.)"""
    init_db()
    with session_scope() as session:
        for delay in in_:
            row = schedule_delayed_check(session, scenario_id, delay, note=note)
            console.print(
                f"[green]scheduled[/green] id={row.id} run_after={row.run_after.isoformat()}"
            )


# ---------- report ----------


@report_app.command("generate")
def report_generate(
    scenario_id: int = typer.Option(..., "--scenario"),
    redact_secrets: bool = typer.Option(
        True, "--redact/--no-redact", help="Mask emails / UUIDs / token-like strings."
    ),
) -> None:
    init_db()
    with session_scope() as session:
        path = generate_markdown_report(session, scenario_id, redact_secrets=redact_secrets)
    console.print(f"[green]wrote report[/green] {path}")


# ---------- observe playwright ----------


@observe_app.command("playwright")
def observe_playwright(
    scenario_id: int = typer.Option(..., "--scenario"),
    phase: str = typer.Option(..., "--phase"),
    url: str = typer.Option(..., "--url"),
    storage_state: Path = typer.Option(
        ...,
        "--storage-state",
        exists=True,
        dir_okay=False,
        readable=True,
        help=(
            "Existing logged-in browser profile (Playwright storage_state.json). "
            "SIL never performs logins."
        ),
    ),
    wait_for: str | None = typer.Option(None, "--wait-for", help="CSS selector to wait for."),
    mask: list[str] = typer.Option(
        [], "--mask", help="CSS selectors to black out before screenshot. Repeatable."
    ),
    timeout_ms: int = typer.Option(15000, "--timeout-ms"),
    note: str = typer.Option("", "--note"),
    label: str = typer.Option("page", "--label"),
) -> None:
    """Capture a screenshot + DOM via Playwright with a pre-existing logged-in
    profile. Authorized scope only."""
    _check_phase(phase)
    init_db()
    try:
        with session_scope() as session:
            shot, html = capture_page(
                session,
                scenario_id,
                phase,
                url=url,
                storage_state=storage_state,
                wait_for=wait_for,
                mask_selectors=mask,
                note=note,
                label=label,
                timeout_ms=timeout_ms,
            )
            console.print(
                f"[green]captured[/green] screenshot id={shot.id} html id={html.id}"
            )
            console.print(f"  screenshot: {shot.artifact_path}")
            console.print(f"  html:       {html.artifact_path}")
    except PlaywrightUnavailable as exc:
        raise typer.BadParameter(str(exc)) from exc
    except StorageStateRequired as exc:
        raise typer.BadParameter(str(exc)) from exc


# ---------- observe api-template ----------


@observe_app.command("api-template")
def observe_api_template(
    scenario_id: int = typer.Option(..., "--scenario"),
    phase: str = typer.Option(..., "--phase"),
    template: str = typer.Option(..., "--template"),
    endpoint: str = typer.Option(..., "--endpoint"),
    max_requests: int = typer.Option(
        ..., "--max-requests", help="Hard cap on requests for this invocation."
    ),
    interval: float | None = typer.Option(
        None, "--interval", help="Seconds between requests (>= template floor)."
    ),
    note: str = typer.Option("", "--note"),
    label: str | None = typer.Option(None, "--label"),
) -> None:
    """Issue a templated, rate-limited API request. Token comes ONLY from the
    template's environment variable."""
    _check_phase(phase)
    init_db()
    with session_scope() as session:
        try:
            obs = fetch_api_template(
                session,
                scenario_id,
                phase,
                template_name=template,
                endpoint=endpoint,
                max_requests=max_requests,
                min_interval_seconds=interval,
                note=note,
                label=label,
            )
        except Exception as exc:
            raise typer.BadParameter(str(exc)) from exc
    console.print(f"[green]recorded api template observation[/green] id={obs.id}")
    console.print(f"  artifact: {obs.artifact_path}")


@observe_app.command("api-templates")
def observe_api_templates_list() -> None:
    """List built-in API templates and their allow-lists."""
    table = Table("name", "base_url", "allowed_endpoints", "token_env")
    for tpl in list_api_templates():
        table.add_row(
            tpl.name,
            tpl.base_url,
            ", ".join(tpl.allowed_endpoints),
            tpl.token_env,
        )
    console.print(table)


# ---------- bundle diff ----------


@diff_app.command("diff")
def bundle_diff_cmd(
    before: Path = typer.Option(..., "--before", exists=True, dir_okay=False, readable=True),
    after: Path = typer.Option(..., "--after", exists=True, dir_okay=False, readable=True),
    keyword: list[str] = typer.Option([], "--keyword", "-k"),
    scenario: int | None = typer.Option(None, "--scenario", help="Save a DiffResult row."),
) -> None:
    """Diff two export bundles (.zip / .tar / .tar.gz)."""
    diff = diff_bundles(before, after, keywords=keyword)
    summary = diff.summary()
    console.print(summary)

    if scenario is not None:
        init_db()
        with session_scope() as session:
            if session.get(Scenario, scenario) is None:
                raise typer.BadParameter(f"scenario id={scenario} not found")
            severity = "info"
            if diff.changed_members:
                severity = "low"
            persistence_count = sum(len(m.persistence) for m in diff.members)
            if persistence_count:
                severity = "needs_review"
            row = DiffResult(
                scenario_id=scenario,
                before_observation_id=0,
                after_observation_id=0,
                diff_type="bundle",
                summary=summary,
                severity_hint=severity,
            )
            session.add(row)
            session.flush()
            console.print(
                f"\n[green]saved bundle diff[/green] id={row.id} severity={severity}"
            )


# ---------- scheduler runner ----------


@scheduler_app.command("run-due")
def scheduler_run_due() -> None:
    """Print prescriptions for delayed checks whose run_after has passed.

    The runner does NOT capture observations itself — it only tells the
    operator what to re-observe."""
    init_db()
    with session_scope() as session:
        items = list_due(session)
        text = render_text(items)
        console.print(text)
        if items:
            console.print(
                f"\n[yellow]{len(items)} due check(s) need operator action."
                "[/yellow] Run `sil scheduler mark-done --check <id>` after each."
            )


@scheduler_app.command("mark-done")
def scheduler_mark_done(
    check_id: int = typer.Option(..., "--check"),
) -> None:
    init_db()
    with session_scope() as session:
        check = mark_done(session, check_id)
        console.print(
            f"[green]marked done[/green] id={check.id} executed_at={check.executed_at}"
        )


def main() -> None:  # pragma: no cover - thin wrapper.
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
