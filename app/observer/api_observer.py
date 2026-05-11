"""API observation.

Two modes:

1. **Operator-supplied** (Phase 1): the operator has already captured an API
   response (curl, devtools, Postman) and hands the body to SIL. No network
   calls are made by the tool.

2. **Templated request** (Phase 2): the operator opts in to a *template* —
   a service-specific request shape with an `allowed_endpoints` allow-list,
   credentials read **only** from environment variables, a mandatory
   `--max-requests` cap, and a forced inter-request delay (default 1s).
   Templates never log in; they assume the operator already minted a token
   on their own account / sandbox tenant.

Phase 2 templates are intentionally minimal. They serve as examples only;
operators MUST verify that the endpoint is in the program's authorized scope
before adding new templates.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.models import Observation, Scenario
from app.storage.artifacts import save_json, save_text, scenario_dir

# ---------------------------------------------------------------------------
# Mode 1 — operator-supplied (was Phase 1; unchanged behavior).
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Mode 2 — templates with strict guards.
# ---------------------------------------------------------------------------


class TemplateNotFound(KeyError):
    pass


class EndpointNotAllowed(ValueError):
    """Raised when an endpoint is not in the template's allow-list."""


class CredentialMissing(RuntimeError):
    """Raised when the required token environment variable is not set."""


class RequestBudgetExceeded(RuntimeError):
    """Raised when the call would exceed the per-invocation `max_requests` cap."""


# Sibling auth surfaces a templated request must NEVER carry, regardless of the
# template's own `auth_header`. The template promises that credentials come
# only from `token_env`; allowing any of these via `extra_headers` would
# silently defeat that promise for in-process Python callers.
_CREDENTIAL_HEADER_DENYLIST: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-access-token",
        "x-csrf-token",
        "x-forwarded-user",
        "x-forwarded-email",
        "x-forwarded-for",
    }
)


@dataclass(frozen=True)
class APITemplate:
    name: str
    description: str
    base_url: str
    allowed_endpoints: tuple[str, ...]
    token_env: str
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    default_min_interval_seconds: float = 1.0
    docs_url: str = ""

    def auth_value(self, token: str) -> str:
        if self.auth_scheme:
            return f"{self.auth_scheme} {token}"
        return token


@dataclass
class _RateState:
    last_call_at: float = 0.0
    calls_made: int = 0


_API_TEMPLATES: dict[str, APITemplate] = {
    "self_account_demo": APITemplate(
        name="self_account_demo",
        description=(
            "Demo template that hits *only* https://httpbin.org/get and "
            "https://httpbin.org/json. Used for tests and as a syntax example."
        ),
        base_url="https://httpbin.org",
        allowed_endpoints=("/get", "/json"),
        token_env="SIL_API_DEMO_TOKEN",
        docs_url="https://httpbin.org/",
    ),
}


def list_api_templates() -> list[APITemplate]:
    return list(_API_TEMPLATES.values())


def fetch_api_template(
    session: Session,
    scenario_id: int,
    phase: str,
    *,
    template_name: str,
    endpoint: str,
    max_requests: int,
    min_interval_seconds: float | None = None,
    extra_headers: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
    note: str = "",
    label: str | None = None,
    state: _RateState | None = None,
    transport: requests.Session | None = None,
) -> Observation:
    """Make a single rate-limited request defined by an API template, then store
    the response as an Observation. Raises before any network call if any guard
    fails."""
    template = _API_TEMPLATES.get(template_name)
    if template is None:
        raise TemplateNotFound(f"unknown template: {template_name}")

    if max_requests is None or max_requests < 1:
        raise ValueError("`max_requests` is required and must be >= 1.")

    if endpoint not in template.allowed_endpoints:
        raise EndpointNotAllowed(
            f"endpoint {endpoint!r} is not in the allow-list for "
            f"template {template.name!r}: {template.allowed_endpoints}"
        )

    token = os.environ.get(template.token_env)
    if not token:
        raise CredentialMissing(
            f"environment variable {template.token_env} is not set. "
            "SIL refuses to read tokens from anywhere else."
        )

    rate_state = state or _RateState()
    if rate_state.calls_made >= max_requests:
        raise RequestBudgetExceeded(
            f"max_requests={max_requests} already consumed in this invocation."
        )

    interval = (
        template.default_min_interval_seconds
        if min_interval_seconds is None
        else min_interval_seconds
    )
    if interval < template.default_min_interval_seconds:
        raise ValueError(
            f"min_interval_seconds={interval} is below template floor "
            f"{template.default_min_interval_seconds}; refusing to relax."
        )
    elapsed = time.time() - rate_state.last_call_at
    if rate_state.last_call_at and elapsed < interval:
        time.sleep(interval - elapsed)

    headers = {template.auth_header: template.auth_value(token)}
    if extra_headers:
        for k, v in extra_headers.items():
            lowered = k.lower()
            if lowered == template.auth_header.lower():
                raise ValueError(
                    f"extra_headers must not override {template.auth_header}; "
                    "auth must come from the template's token_env."
                )
            if lowered in _CREDENTIAL_HEADER_DENYLIST:
                raise ValueError(
                    f"extra_headers must not carry credential-bearing header {k!r}; "
                    "the template guarantees credentials come only from token_env."
                )
            headers[k] = v

    url = template.base_url.rstrip("/") + endpoint
    http = transport or requests.Session()
    response = http.get(url, headers=headers, timeout=timeout_seconds)
    rate_state.last_call_at = time.time()
    rate_state.calls_made += 1

    body_text = response.text
    status_code = response.status_code

    return record_api_response(
        session,
        scenario_id,
        phase,
        body_text=body_text,
        endpoint=f"{template.name}:{endpoint}",
        status_code=status_code,
        note=note or f"templated request to {url}",
        label=label or f"{template.name}_{endpoint.strip('/').replace('/', '_') or 'root'}",
    )
