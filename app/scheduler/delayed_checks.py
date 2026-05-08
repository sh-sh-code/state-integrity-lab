"""Phase 1 delayed-check scheduler.

The scheduler only writes rows to the database; it does NOT spawn background
processes. Phase 2 will wire `cron`/`systemd` (or APScheduler) to actually
trigger the re-observation prompt at the recorded time.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DelayedCheck, Scenario

DEFAULT_DELAYS: tuple[str, ...] = ("5m", "1h", "24h")

_DELAY_RE = re.compile(r"^(\d+)\s*(s|m|h|d)$")


def parse_delay(value: str) -> timedelta:
    """Parse strings like `5m`, `1h`, `24h`, `7d`."""
    match = _DELAY_RE.match(value.strip().lower())
    if not match:
        raise ValueError(
            f"Invalid delay {value!r}. Use Ns / Nm / Nh / Nd (e.g. '5m', '24h')."
        )
    amount = int(match.group(1))
    unit = match.group(2)
    factors = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return timedelta(seconds=amount * factors[unit])


def schedule_delayed_check(
    session: Session,
    scenario_id: int,
    delay: str,
    *,
    note: str = "",
    now: datetime | None = None,
) -> DelayedCheck:
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise ValueError(f"Scenario id={scenario_id} not found.")
    base = now or datetime.now(timezone.utc)
    run_after = base + parse_delay(delay)
    check = DelayedCheck(
        scenario_id=scenario.id,
        run_after=run_after,
        note=note or f"re-observe {scenario.name} after {delay}",
    )
    session.add(check)
    session.flush()
    return check


def list_due_checks(session: Session, *, now: datetime | None = None) -> list[DelayedCheck]:
    base = now or datetime.now(timezone.utc)
    stmt = (
        select(DelayedCheck)
        .where(DelayedCheck.executed_at.is_(None))
        .where(DelayedCheck.run_after <= base)
        .order_by(DelayedCheck.run_after)
    )
    return list(session.scalars(stmt).all())
