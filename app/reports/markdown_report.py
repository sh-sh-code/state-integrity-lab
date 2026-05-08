"""Generate Bug-Bounty / QA / audit-ready Markdown reports."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import (
    DelayedCheck,
    DiffResult,
    Observation,
    Report,
    Scenario,
    Transition,
)

_REDACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "[REDACTED_UUID]"),
    (re.compile(r"\b(sk|pk|key|token|api)[_-][A-Za-z0-9_-]{8,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._-]{12,}\b"), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
)


def redact(text: str) -> str:
    out = text
    for pattern, replacement in _REDACT_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def _maybe_redact(text: str, do_redact: bool) -> str:
    return redact(text) if do_redact else text


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _section_observations(
    observations: Iterable[Observation],
    do_redact: bool,
) -> list[str]:
    lines: list[str] = []
    by_phase: dict[str, list[Observation]] = {"before": [], "after": [], "delayed_after": []}
    for obs in observations:
        by_phase.setdefault(obs.phase, []).append(obs)

    for phase in ("before", "after", "delayed_after"):
        items = by_phase.get(phase, [])
        if not items:
            continue
        lines.append(f"### Phase: `{phase}`")
        lines.append("")
        for obs in sorted(items, key=lambda o: o.created_at):
            lines.append(
                f"- **#{obs.id}** `{obs.observer_type}` at {_format_dt(obs.created_at)}"
            )
            if obs.artifact_path:
                lines.append(f"  - artifact: `{obs.artifact_path}`")
            if obs.note:
                snippet = _maybe_redact(obs.note.strip(), do_redact)
                lines.append(f"  - note: {snippet}")
        lines.append("")
    return lines


def _section_transitions(transitions: Iterable[Transition], do_redact: bool) -> list[str]:
    lines: list[str] = []
    items = sorted(transitions, key=lambda t: t.created_at)
    if not items:
        lines.append("_No transitions recorded._")
        lines.append("")
        return lines
    for t in items:
        lines.append(
            f"- **#{t.id}** `{t.transition_type}` by `{t.performed_by}` "
            f"at {_format_dt(t.created_at)}"
        )
        if t.note:
            lines.append(f"  - note: {_maybe_redact(t.note.strip(), do_redact)}")
    lines.append("")
    return lines


def _section_diffs(diffs: Iterable[DiffResult], do_redact: bool) -> list[str]:
    lines: list[str] = []
    items = sorted(diffs, key=lambda d: (d.severity_hint, d.created_at))
    if not items:
        lines.append("_No diff results recorded._")
        lines.append("")
        return lines
    for d in items:
        lines.append(
            f"#### Diff #{d.id} — `{d.diff_type}` (severity hint: `{d.severity_hint}`)"
        )
        lines.append(
            f"- before observation: `#{d.before_observation_id}`, "
            f"after observation: `#{d.after_observation_id}`"
        )
        lines.append(f"- recorded at: {_format_dt(d.created_at)}")
        if d.summary:
            summary = _maybe_redact(d.summary, do_redact)
            lines.append("")
            lines.append("```text")
            lines.append(summary.rstrip())
            lines.append("```")
        lines.append("")
    return lines


def _section_delayed(delays: Iterable[DelayedCheck]) -> list[str]:
    lines: list[str] = []
    items = sorted(delays, key=lambda d: d.run_after)
    if not items:
        lines.append("_No delayed checks scheduled._")
        lines.append("")
        return lines
    for d in items:
        status = "executed" if d.executed_at else "pending"
        lines.append(
            f"- **#{d.id}** run_after={_format_dt(d.run_after)} status={status}"
        )
        if d.note:
            lines.append(f"  - note: {d.note}")
    lines.append("")
    return lines


def _do_no_harm_block() -> list[str]:
    return [
        "## Scope & Safety Statement",
        "",
        "- All observations were performed on the operator's own account, on test data,",
        "  or within an explicitly authorized Bug Bounty / audit scope.",
        "- No authentication bypass, rate-limit evasion, DoS, or third-party data access",
        "  was attempted.",
        "- Sensitive identifiers in this report have been redacted where the",
        "  generator could detect them. Human review is still required before sharing.",
        "",
    ]


def generate_markdown_report(
    session: Session,
    scenario_id: int,
    *,
    settings: Settings | None = None,
    redact_secrets: bool | None = None,
) -> Path:
    settings = settings or get_settings()
    settings.ensure_dirs()
    do_redact = settings.redact_by_default if redact_secrets is None else redact_secrets

    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise ValueError(f"Scenario id={scenario_id} not found.")

    timestamp = datetime.now(timezone.utc)
    filename = (
        f"scenario_{scenario.id:04d}_"
        f"{re.sub(r'[^a-z0-9._-]+', '-', scenario.name.lower()).strip('-')}_"
        f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}.md"
    )
    output_path = settings.reports_dir / filename

    lines: list[str] = []
    lines.append(f"# State Integrity Lab Report — {scenario.name}")
    lines.append("")
    lines.append(f"- **Scenario ID**: `{scenario.id}`")
    lines.append(f"- **Target service**: `{_maybe_redact(scenario.target_service, do_redact)}`")
    lines.append(f"- **Template**: `{scenario.template or '—'}`")
    lines.append(f"- **Status**: `{scenario.status}`")
    lines.append(f"- **Created**: {_format_dt(scenario.created_at)}")
    lines.append(f"- **Generated**: {_format_dt(timestamp)}")
    lines.append("")
    lines.append("## Hypothesis")
    lines.append("")
    lines.append(_maybe_redact(scenario.hypothesis or "_(no hypothesis recorded)_", do_redact))
    lines.append("")

    lines.extend(_do_no_harm_block())

    lines.append("## Observations")
    lines.append("")
    lines.extend(_section_observations(scenario.observations, do_redact))

    lines.append("## Transitions")
    lines.append("")
    lines.extend(_section_transitions(scenario.transitions, do_redact))

    lines.append("## Diff results")
    lines.append("")
    lines.extend(_section_diffs(scenario.diffs, do_redact))

    lines.append("## Delayed checks")
    lines.append("")
    lines.extend(_section_delayed(scenario.delayed_checks))

    lines.append("## Operator notes")
    lines.append("")
    lines.append("_Add manual narrative, screenshots, or remediation suggestions here._")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")

    report = Report(scenario_id=scenario.id, markdown_path=str(output_path))
    session.add(report)
    session.flush()
    return output_path
