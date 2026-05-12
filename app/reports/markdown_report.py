"""Generate Bug-Bounty / QA / audit-ready Markdown reports."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.findings import linked_diff_ids
from app.models import (
    DelayedCheck,
    DiffResult,
    Finding,
    Observation,
    Report,
    Scenario,
    ScenarioMetadata,
    Transition,
)

_REDACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "[REDACTED_UUID]"),
    # PEM private-key blocks (any flavour: RSA, EC, OPENSSH, etc.).
    (
        re.compile(
            r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----[\s\S]+?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # JWTs (three base64url segments).
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
        "[REDACTED_JWT]",
    ),
    # GitHub Personal Access Tokens / OAuth / app / refresh / server tokens.
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    # Slack tokens.
    (re.compile(r"\bxox[abprsoe]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    # Google API keys.
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[REDACTED_GOOGLE_API_KEY]"),
    # AWS access key IDs.
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY_ID]"),
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
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%SZ")


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
                path_display = _maybe_redact(obs.artifact_path, do_redact)
                lines.append(f"  - artifact: `{path_display}`")
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


_PLACEHOLDER = "_(to be filled in by the operator before submission — see `sil scenario annotate --help`)_"


def _prose_section(title: str, value: str, do_redact: bool) -> list[str]:
    body = _maybe_redact(value.strip(), do_redact) if value and value.strip() else _PLACEHOLDER
    return [f"## {title}", "", body, ""]


def _section_scope_and_auth(meta: ScenarioMetadata | None, do_redact: bool) -> list[str]:
    return _prose_section(
        "Scope and Authorization",
        meta.scope_authorization if meta else "",
        do_redact,
    )


def _section_test_data(meta: ScenarioMetadata | None, do_redact: bool) -> list[str]:
    return _prose_section(
        "Test Data Used",
        meta.test_data_used if meta else "",
        do_redact,
    )


def _section_expected_actual(
    scenario: Scenario, meta: ScenarioMetadata | None, do_redact: bool
) -> list[str]:
    expected = (meta.expected_behavior if meta else "") or scenario.hypothesis
    actual = meta.actual_behavior if meta else ""
    out = ["## Expected vs Actual", ""]
    out.append("**Expected:**")
    out.append("")
    out.append(_maybe_redact(expected.strip(), do_redact) if expected.strip() else _PLACEHOLDER)
    out.append("")
    out.append("**Actual:**")
    out.append("")
    out.append(_maybe_redact(actual.strip(), do_redact) if actual.strip() else _PLACEHOLDER)
    out.append("")
    return out


def _section_security_impact(meta: ScenarioMetadata | None, do_redact: bool) -> list[str]:
    return _prose_section(
        "Security Impact",
        meta.security_impact if meta else "",
        do_redact,
    )


def _section_limitations(meta: ScenarioMetadata | None, do_redact: bool) -> list[str]:
    return _prose_section(
        "Limitations",
        meta.limitations if meta else "",
        do_redact,
    )


def _section_recommended_fix(meta: ScenarioMetadata | None, do_redact: bool) -> list[str]:
    return _prose_section(
        "Recommended Fix Direction",
        meta.recommended_fix if meta else "",
        do_redact,
    )


_SEVERITY_ORDER: dict[str, int] = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def _section_findings(findings: Iterable[Finding], do_redact: bool) -> list[str]:
    items = list(findings)
    out = ["## Findings", ""]
    if not items:
        out.append("_No findings recorded yet._")
        out.append("")
        return out
    items.sort(
        key=lambda f: (-_SEVERITY_ORDER.get(f.severity, 0), f.created_at),
    )
    for f in items:
        title = _maybe_redact(f.title, do_redact)
        out.append(f"### Finding #{f.id} — {title}")
        out.append("")
        out.append(f"- severity: `{f.severity}`")
        out.append(f"- status:   `{f.status}`")
        if f.external_id:
            out.append(f"- external_id: `{_maybe_redact(f.external_id, do_redact)}`")
        diffs = linked_diff_ids(f)
        if diffs:
            out.append(f"- linked diffs: {', '.join(f'#{d}' for d in diffs)}")
        if f.bounty_amount is not None:
            out.append(
                f"- bounty: `{f.bounty_amount} {f.bounty_currency or '?'}`"
            )
        out.append(f"- created: {_format_dt(f.created_at)}")
        if f.closed_at:
            out.append(f"- closed:  {_format_dt(f.closed_at)}")
        if f.description:
            out.append("")
            out.append(_maybe_redact(f.description.strip(), do_redact))
        if f.note:
            out.append("")
            out.append("_Note:_ " + _maybe_redact(f.note.strip(), do_redact))
        out.append("")
    return out


def _section_evidence(scenario: Scenario, do_redact: bool) -> list[str]:
    """Compact, deduplicated list of artifact paths grouped by phase.

    Useful as the "Evidence" section in a Bug Bounty report — the operator
    points reviewers at the underlying SIL artifact directory.
    """
    out = ["## Evidence", ""]
    by_phase: dict[str, list[Observation]] = {}
    for obs in scenario.observations:
        by_phase.setdefault(obs.phase, []).append(obs)
    if not by_phase:
        out.append("_No observations recorded._")
        out.append("")
        return out
    for phase in ("before", "after", "delayed_after"):
        items = by_phase.get(phase, [])
        if not items:
            continue
        out.append(f"### {phase}")
        out.append("")
        for obs in sorted(items, key=lambda o: o.created_at):
            if obs.artifact_path:
                path_display = _maybe_redact(obs.artifact_path, do_redact)
                out.append(f"- `{path_display}` ({obs.observer_type})")
        out.append("")
    out.append(
        "_Reviewers should request the artifact directory or the report bundle "
        "rather than a forward of secrets via chat._"
    )
    out.append("")
    return out


def _section_timeline(scenario: Scenario) -> list[str]:
    """Auto-built timeline interleaving observations, transitions, and delayed checks."""
    events: list[tuple[datetime, str]] = []
    for obs in scenario.observations:
        events.append(
            (
                obs.created_at,
                f"observe[{obs.phase}] #{obs.id} {obs.observer_type}",
            )
        )
    for tr in scenario.transitions:
        events.append((tr.created_at, f"transition #{tr.id} {tr.transition_type} by {tr.performed_by}"))
    for d in scenario.delayed_checks:
        events.append((d.run_after, f"delayed_check #{d.id} due"))
        if d.executed_at:
            events.append((d.executed_at, f"delayed_check #{d.id} executed"))
    for diff in scenario.diffs:
        events.append((diff.created_at, f"diff #{diff.id} {diff.diff_type} -> {diff.severity_hint}"))

    out = ["## Timeline", ""]
    if not events:
        out.append("_No events recorded._")
        out.append("")
        return out
    events.sort(key=lambda e: e[0])
    for ts, label in events:
        out.append(f"- {_format_dt(ts)} — {label}")
    out.append("")
    return out


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

    timestamp = datetime.now(UTC)
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

    meta = scenario.metadata_row
    lines.extend(_section_scope_and_auth(meta, do_redact))
    lines.extend(_section_test_data(meta, do_redact))
    lines.extend(_section_timeline(scenario))
    lines.extend(_section_expected_actual(scenario, meta, do_redact))
    lines.extend(_section_security_impact(meta, do_redact))

    lines.append("## Observations")
    lines.append("")
    lines.extend(_section_observations(scenario.observations, do_redact))

    lines.append("## Transitions")
    lines.append("")
    lines.extend(_section_transitions(scenario.transitions, do_redact))

    lines.append("## Diff results")
    lines.append("")
    lines.extend(_section_diffs(scenario.diffs, do_redact))

    lines.extend(_section_findings(scenario.findings, do_redact))

    lines.extend(_section_evidence(scenario, do_redact))

    lines.append("## Delayed checks")
    lines.append("")
    lines.extend(_section_delayed(scenario.delayed_checks))

    lines.extend(_section_limitations(meta, do_redact))
    lines.extend(_section_recommended_fix(meta, do_redact))

    lines.append("## Operator notes")
    lines.append("")
    lines.append("_Add manual narrative, screenshots, or remediation suggestions here._")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")

    report = Report(scenario_id=scenario.id, markdown_path=str(output_path))
    session.add(report)
    session.flush()
    return output_path
