from __future__ import annotations

from app.db import session_scope
from app.models import Observation, Scenario, Transition


def _make_scenario(name: str = "test_scn") -> int:
    with session_scope() as session:
        scenario = Scenario(
            name=name,
            target_service="example.com",
            hypothesis="things should be cleaned up",
            template="connector_revoke_persistence",
        )
        session.add(scenario)
        session.flush()
        return scenario.id


def test_scenario_can_be_created_and_listed() -> None:
    sid = _make_scenario()
    with session_scope() as session:
        scenarios = session.query(Scenario).all()
        assert len(scenarios) == 1
        assert scenarios[0].id == sid
        assert scenarios[0].status == "draft"
        assert scenarios[0].template == "connector_revoke_persistence"


def test_observation_round_trip() -> None:
    sid = _make_scenario()
    with session_scope() as session:
        obs = Observation(
            scenario_id=sid,
            phase="before",
            observer_type="manual",
            artifact_path=None,
            note="captured manually",
        )
        session.add(obs)
        session.flush()
        oid = obs.id

    with session_scope() as session:
        obs = session.get(Observation, oid)
        assert obs is not None
        assert obs.scenario_id == sid
        assert obs.phase == "before"
        assert obs.observer_type == "manual"
        assert obs.note == "captured manually"


def test_transition_round_trip() -> None:
    sid = _make_scenario("permission_scn")
    with session_scope() as session:
        t = Transition(
            scenario_id=sid,
            transition_type="downgraded_permission",
            performed_by="human",
            note="admin -> viewer",
        )
        session.add(t)
        session.flush()
        tid = t.id

    with session_scope() as session:
        t = session.get(Transition, tid)
        assert t is not None
        assert t.transition_type == "downgraded_permission"
        assert t.performed_by == "human"


def test_cascade_delete_removes_children() -> None:
    sid = _make_scenario("cascade_scn")
    with session_scope() as session:
        session.add(
            Observation(
                scenario_id=sid,
                phase="before",
                observer_type="manual",
                note="x",
            )
        )
        session.add(
            Transition(
                scenario_id=sid,
                transition_type="deleted_file",
                performed_by="human",
                note="x",
            )
        )

    with session_scope() as session:
        scenario = session.get(Scenario, sid)
        assert scenario is not None
        session.delete(scenario)

    with session_scope() as session:
        assert session.query(Observation).count() == 0
        assert session.query(Transition).count() == 0
