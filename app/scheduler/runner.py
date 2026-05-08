"""Phase 2 delayed-check runner.

The runner is intentionally NOT an automated observer. It walks rows in
`delayed_checks` whose `run_after` has passed and prints the prescription
for the operator to follow. Marking `executed_at` records that the operator
has acted on the prompt.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DelayedCheck, Scenario


@dataclass
class DuePrescription:
    check: DelayedCheck
    scenario: Scenario
    prescriptions: list[str]


def _build_prescriptions(scenario: Scenario, check: DelayedCheck) -> list[str]:
    sid = scenario.id
    return [
        f"# delayed re-observation due for scenario {sid} ({scenario.name})",
        f"# scheduled at: {check.run_after.isoformat()}",
        f"# note: {check.note or '(none)'}",
        "",
        "1. Re-capture the SAME surfaces you captured in the `after` phase.",
        "   Use the same query / URL / export options.",
        "",
        f"   sil observe html       --scenario {sid} --phase delayed_after --file ./snapshot.html",
        f"   sil observe screenshot --scenario {sid} --phase delayed_after --file ./shot.png",
        f"   sil observe json       --scenario {sid} --phase delayed_after --file ./payload.json",
        "",
        "2. Diff against the `after` observation, NOT the `before` observation.",
        "   sil diff --before <after_obs_id> --after <delayed_obs_id> --keyword <kw>",
        "",
        "3. When done, mark this check executed:",
        f"   sil scheduler mark-done --check {check.id}",
    ]


def list_due(session: Session, *, now: datetime | None = None) -> list[DuePrescription]:
    base = now or datetime.now(UTC)
    stmt = (
        select(DelayedCheck)
        .where(DelayedCheck.executed_at.is_(None))
        .where(DelayedCheck.run_after <= base)
        .order_by(DelayedCheck.run_after)
    )
    out: list[DuePrescription] = []
    for check in session.scalars(stmt).all():
        scenario = check.scenario
        out.append(DuePrescription(check=check, scenario=scenario, prescriptions=_build_prescriptions(scenario, check)))
    return out


def mark_done(session: Session, check_id: int, *, now: datetime | None = None) -> DelayedCheck:
    check = session.get(DelayedCheck, check_id)
    if check is None:
        raise ValueError(f"DelayedCheck id={check_id} not found.")
    check.executed_at = now or datetime.now(UTC)
    session.flush()
    return check


def render_text(items: Iterable[DuePrescription]) -> str:
    if not items:
        return "No delayed checks are due."
    blocks: list[str] = []
    for item in items:
        blocks.append("\n".join(item.prescriptions))
    return "\n\n---\n\n".join(blocks)
