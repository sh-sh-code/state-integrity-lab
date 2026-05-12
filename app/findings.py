"""Findings registry — operator-curated findings tied to a scenario.

A `Finding` row sits on top of one or more auto-generated `DiffResult`
rows and represents what the operator has decided is worth tracking
through the Bug Bounty / QA triage lifecycle. The CLI surfaces are in
`app.cli`; this module owns the state-machine + validation.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import (
    FINDING_SEVERITIES,
    FINDING_STATUSES,
    DiffResult,
    Finding,
    Scenario,
)

# Statuses that count as "done" (closed_at is filled).
_TERMINAL_STATUSES: frozenset[str] = frozenset({"fixed", "wont_fix", "duplicate"})


class FindingError(ValueError):
    """Raised when an invalid value is passed to a registry call."""


def _validate_severity(value: str) -> None:
    if value not in FINDING_SEVERITIES:
        raise FindingError(
            f"severity must be one of {FINDING_SEVERITIES}, got {value!r}"
        )


def _validate_status(value: str) -> None:
    if value not in FINDING_STATUSES:
        raise FindingError(f"status must be one of {FINDING_STATUSES}, got {value!r}")


def _parse_diff_ids(value: str) -> list[int]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    out: list[int] = []
    for item in loaded:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _serialize_diff_ids(ids: Iterable[int]) -> str:
    return json.dumps(sorted({int(i) for i in ids}))


def open_finding(
    session: Session,
    scenario_id: int,
    *,
    title: str,
    description: str = "",
    severity: str = "medium",
    diff_ids: Iterable[int] | None = None,
    external_id: str = "",
    note: str = "",
) -> Finding:
    """Create a new finding in `open` state."""
    if not title.strip():
        raise FindingError("title is required")
    _validate_severity(severity)
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise FindingError(f"scenario id={scenario_id} not found")

    diff_id_list: list[int] = []
    if diff_ids:
        for diff_id in diff_ids:
            diff = session.get(DiffResult, int(diff_id))
            if diff is None:
                raise FindingError(f"diff id={diff_id} not found")
            if diff.scenario_id != scenario_id:
                raise FindingError(
                    f"diff id={diff_id} belongs to scenario {diff.scenario_id}, "
                    f"not {scenario_id}"
                )
            diff_id_list.append(diff.id)

    finding = Finding(
        scenario_id=scenario_id,
        title=title.strip(),
        description=description,
        severity=severity,
        status="open",
        external_id=external_id,
        diff_ids=_serialize_diff_ids(diff_id_list),
        note=note,
    )
    session.add(finding)
    session.flush()
    return finding


def update_finding(
    session: Session,
    finding_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    external_id: str | None = None,
    note: str | None = None,
    bounty_amount: int | None = None,
    bounty_currency: str | None = None,
) -> Finding:
    """Update mutable fields. Setting status to a terminal value also stamps
    closed_at; setting status back to a non-terminal value clears it."""
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise FindingError(f"finding id={finding_id} not found")

    if title is not None:
        stripped = title.strip()
        if not stripped:
            raise FindingError("title cannot be empty")
        finding.title = stripped
    if description is not None:
        finding.description = description
    if severity is not None:
        _validate_severity(severity)
        finding.severity = severity
    if status is not None:
        _validate_status(status)
        finding.status = status
        if status in _TERMINAL_STATUSES and finding.closed_at is None:
            finding.closed_at = datetime.now(UTC)
        if status not in _TERMINAL_STATUSES:
            finding.closed_at = None
    if external_id is not None:
        finding.external_id = external_id
    if note is not None:
        finding.note = note
    if bounty_amount is not None:
        finding.bounty_amount = bounty_amount
    if bounty_currency is not None:
        finding.bounty_currency = bounty_currency
    session.flush()
    return finding


def list_findings(
    session: Session,
    *,
    scenario_id: int | None = None,
    status: str | None = None,
) -> list[Finding]:
    query = session.query(Finding)
    if scenario_id is not None:
        query = query.filter(Finding.scenario_id == scenario_id)
    if status is not None:
        _validate_status(status)
        query = query.filter(Finding.status == status)
    return query.order_by(Finding.created_at).all()


def linked_diff_ids(finding: Finding) -> list[int]:
    return _parse_diff_ids(finding.diff_ids)
