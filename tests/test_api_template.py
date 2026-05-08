"""Tests for the API template observer.

These tests must NOT make real network calls. We inject a fake
`requests.Session` via the `transport=` parameter.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from app.db import session_scope
from app.models import Scenario
from app.observer.api_observer import (
    CredentialMissing,
    EndpointNotAllowed,
    RequestBudgetExceeded,
    TemplateNotFound,
    _RateState,
    fetch_api_template,
)


class _FakeResponse:
    def __init__(self, body: dict[str, Any], status_code: int = 200) -> None:
        self.status_code = status_code
        self.text = json.dumps(body)


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, headers: dict[str, str], timeout: float) -> _FakeResponse:
        self.calls.append((url, headers))
        return self.response


def _make_scenario() -> int:
    with session_scope() as session:
        scenario = Scenario(name="api_scn", target_service="httpbin", hypothesis="x")
        session.add(scenario)
        session.flush()
        return scenario.id


def test_unknown_template_rejected() -> None:
    sid = _make_scenario()
    with session_scope() as session:
        with pytest.raises(TemplateNotFound):
            fetch_api_template(
                session,
                sid,
                "before",
                template_name="does_not_exist",
                endpoint="/get",
                max_requests=1,
            )


def test_endpoint_not_in_allowlist_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _make_scenario()
    monkeypatch.setenv("SIL_API_DEMO_TOKEN", "x")
    with session_scope() as session:
        with pytest.raises(EndpointNotAllowed):
            fetch_api_template(
                session,
                sid,
                "before",
                template_name="self_account_demo",
                endpoint="/admin/users",
                max_requests=1,
            )


def test_missing_token_env_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _make_scenario()
    monkeypatch.delenv("SIL_API_DEMO_TOKEN", raising=False)
    with session_scope() as session:
        with pytest.raises(CredentialMissing):
            fetch_api_template(
                session,
                sid,
                "before",
                template_name="self_account_demo",
                endpoint="/get",
                max_requests=1,
            )


def test_budget_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _make_scenario()
    monkeypatch.setenv("SIL_API_DEMO_TOKEN", "secret")
    state = _RateState(calls_made=1)
    with session_scope() as session:
        with pytest.raises(RequestBudgetExceeded):
            fetch_api_template(
                session,
                sid,
                "before",
                template_name="self_account_demo",
                endpoint="/get",
                max_requests=1,
                state=state,
            )


def test_interval_below_floor_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _make_scenario()
    monkeypatch.setenv("SIL_API_DEMO_TOKEN", "secret")
    with session_scope() as session:
        with pytest.raises(ValueError):
            fetch_api_template(
                session,
                sid,
                "before",
                template_name="self_account_demo",
                endpoint="/get",
                max_requests=1,
                min_interval_seconds=0.1,
            )


def test_extra_headers_cannot_override_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _make_scenario()
    monkeypatch.setenv("SIL_API_DEMO_TOKEN", "secret")
    with session_scope() as session:
        with pytest.raises(ValueError):
            fetch_api_template(
                session,
                sid,
                "before",
                template_name="self_account_demo",
                endpoint="/get",
                max_requests=1,
                extra_headers={"Authorization": "Bearer evil"},
            )


def test_successful_call_records_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _make_scenario()
    monkeypatch.setenv("SIL_API_DEMO_TOKEN", "secret-token-value")
    fake = _FakeSession(_FakeResponse({"ok": True}))

    with session_scope() as session:
        obs = fetch_api_template(
            session,
            sid,
            "before",
            template_name="self_account_demo",
            endpoint="/get",
            max_requests=1,
            transport=fake,
        )
        assert obs.id is not None
        assert obs.observer_type == "api"
        assert obs.scenario_id == sid
        artifact_path = obs.artifact_path

    # Token was sent in Authorization header, not leaked elsewhere.
    assert len(fake.calls) == 1
    url, headers = fake.calls[0]
    assert url == "https://httpbin.org/get"
    assert headers["Authorization"] == "Bearer secret-token-value"
    # Token must NOT have been recorded into the artifact.
    artifact_text = open(artifact_path).read()  # noqa: SIM115
    assert "secret-token-value" not in artifact_text
