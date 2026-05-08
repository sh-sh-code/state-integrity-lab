"""Placeholder API-observer helpers.

Phase 1 only stores API responses that the operator captured themselves
(e.g. via curl, Postman, or the browser devtools) - the tool does NOT make
unauthorized network requests. Phase 2 will add authenticated, scope-aware
templates the operator opts into per service.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import Observation, Scenario
from app.storage.artifacts import save_json, save_text, scenario_dir


def record_api_response(
    session: Session,
    scenario_id: int,
    phase: str,
    *,
    body: Any | None = None,
    body_text: str | None = None,
    endpoint: str = "",
    status_code: int | None = None,
    note: str = "",
    label: str = "api_response",
) -> Observation:
    """Record an API response artifact.

    Provide either `body` (parsed JSON-compatible object) or `body_text`
    (raw response body). Endpoint / status are stored as metadata.
    """
    if body is None and body_text is None:
        raise ValueError("Provide `body=` or `body_text=`.")
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise ValueError(f"Scenario id={scenario_id} not found.")
    target = scenario_dir(scenario.id, scenario.name, phase)

    metadata = {
        "endpoint": endpoint,
        "status_code": status_code,
        "note": note,
    }
    if body is not None:
        payload = {"metadata": metadata, "body": body}
        artifact = save_json(target, label, payload)
    else:
        # Try to parse as JSON for nicer downstream diffs; fall back to text.
        assert body_text is not None
        try:
            parsed = json.loads(body_text)
            payload = {"metadata": metadata, "body": parsed}
            artifact = save_json(target, label, payload)
        except Exception:
            artifact = save_text(target, label, body_text, suffix=".txt")

    observation = Observation(
        scenario_id=scenario.id,
        phase=phase,
        observer_type="api",
        artifact_path=str(artifact),
        note=note or endpoint,
    )
    session.add(observation)
    session.flush()
    return observation
