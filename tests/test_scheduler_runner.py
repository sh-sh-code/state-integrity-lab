from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import session_scope
from app.models import Scenario
from app.scheduler import (
    list_due,
    mark_done,
    render_text,
    schedule_delayed_check,
)


def _make_scenario() -> int:
    with session_scope() as session:
        scenario = Scenario(
            name="runner_scn",
            target_service="example.com",
            hypothesis="x",
        )
        session.add(scenario)
        session.flush()
        return scenario.id


def test_list_due_returns_only_past_unexecuted_checks() -> None:
    sid = _make_scenario()
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=1)

    with session_scope() as session:
        due_check = schedule_delayed_check(
            session, sid, "5m", note="due", now=past
        )
        future_check = schedule_delayed_check(  # noqa: F841
            session, sid, "1h", note="not due"
        )
        due_id = due_check.id

    with session_scope() as session:
        items = list_due(session)
        ids = [item.check.id for item in items]
        assert due_id in ids
        # `list_due` filters server-side; only one of the two should be due.
        assert len(items) == 1
        text = render_text(items)
        assert f"scenario {sid}" in text
        assert "sil scheduler mark-done" in text


def test_mark_done_sets_executed_at() -> None:
    sid = _make_scenario()
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    with session_scope() as session:
        check = schedule_delayed_check(session, sid, "5m", note="x", now=past)
        cid = check.id

    with session_scope() as session:
        check = mark_done(session, cid)
        assert check.executed_at is not None

    with session_scope() as session:
        items = list_due(session)
        assert all(item.check.id != cid for item in items)


def test_render_text_when_nothing_due() -> None:
    assert render_text([]) == "No delayed checks are due."
