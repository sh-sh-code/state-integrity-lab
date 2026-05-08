"""Human-driven observation helpers.

The Phase 1 observation flow is intentionally manual:
the operator browses the target service themselves (logged in as their own
account, on permitted scope only) and hands the resulting artifact to the
CLI. These helpers persist the artifact under `artifacts/` and write an
`Observation` row pointing at it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import Observation, Scenario
from app.storage.artifacts import (
    copy_artifact,
    save_html,
    save_json,
    save_text,
    scenario_dir,
)


def _scenario_or_raise(session: Session, scenario_id: int) -> Scenario:
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise ValueError(f"Scenario id={scenario_id} not found.")
    return scenario


def _record(
    session: Session,
    scenario_id: int,
    phase: str,
    observer_type: str,
    artifact_path: Path | None,
    note: str,
) -> Observation:
    observation = Observation(
        scenario_id=scenario_id,
        phase=phase,
        observer_type=observer_type,
        artifact_path=str(artifact_path) if artifact_path else None,
        note=note,
    )
    session.add(observation)
    session.flush()
    return observation


def record_manual(
    session: Session,
    scenario_id: int,
    phase: str,
    note: str,
    *,
    label: str = "manual",
) -> Observation:
    scenario = _scenario_or_raise(session, scenario_id)
    target = scenario_dir(scenario.id, scenario.name, phase)
    artifact = save_text(target, label, note, suffix=".md")
    return _record(session, scenario.id, phase, "manual", artifact, note)


def record_screenshot(
    session: Session,
    scenario_id: int,
    phase: str,
    source_path: Path,
    note: str = "",
    *,
    label: str | None = None,
) -> Observation:
    scenario = _scenario_or_raise(session, scenario_id)
    target = scenario_dir(scenario.id, scenario.name, phase)
    artifact = copy_artifact(target, source_path, label=label or "screenshot")
    return _record(session, scenario.id, phase, "screenshot", artifact, note)


def record_html(
    session: Session,
    scenario_id: int,
    phase: str,
    *,
    content: str | None = None,
    source_path: Path | None = None,
    note: str = "",
    label: str = "snapshot",
) -> Observation:
    if content is None and source_path is None:
        raise ValueError("Provide either `content=` or `source_path=`.")
    scenario = _scenario_or_raise(session, scenario_id)
    target = scenario_dir(scenario.id, scenario.name, phase)
    if content is not None:
        artifact = save_html(target, label, content)
    else:
        assert source_path is not None
        artifact = copy_artifact(target, source_path, label=label)
    return _record(session, scenario.id, phase, "html", artifact, note)


def record_json(
    session: Session,
    scenario_id: int,
    phase: str,
    *,
    payload: Any | None = None,
    source_path: Path | None = None,
    note: str = "",
    label: str = "payload",
) -> Observation:
    if payload is None and source_path is None:
        raise ValueError("Provide either `payload=` or `source_path=`.")
    scenario = _scenario_or_raise(session, scenario_id)
    target = scenario_dir(scenario.id, scenario.name, phase)
    if payload is not None:
        artifact = save_json(target, label, payload)
    else:
        assert source_path is not None
        # Validate that the file is JSON before storing it.
        try:
            json.loads(source_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Source file is not valid JSON: {exc}") from exc
        artifact = copy_artifact(target, source_path, label=label)
    return _record(session, scenario.id, phase, "json", artifact, note)
