"""Tests for the Phase 1.5 security-review hardenings."""

from __future__ import annotations

import pytest

from app.observer.api_observer import _RateState, fetch_api_template
from app.reports.markdown_report import redact


# ---- A: richer redact patterns --------------------------------------------


def test_redact_masks_jwt() -> None:
    sample = (
        "token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c here"
    )
    out = redact(sample)
    assert "eyJhbGciOi" not in out
    assert "[REDACTED_JWT]" in out


def test_redact_masks_github_pat() -> None:
    for prefix in ("ghp", "gho", "ghu", "ghs", "ghr"):
        sample = f"token={prefix}_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        out = redact(sample)
        assert f"{prefix}_AAAA" not in out
        assert "[REDACTED_GITHUB_TOKEN]" in out


def test_redact_masks_slack_token() -> None:
    for prefix in ("xoxb", "xoxa", "xoxp", "xoxr", "xoxs"):
        sample = f"slack {prefix}-1234567890-abcdef1234567890"
        out = redact(sample)
        assert prefix + "-" not in out


def test_redact_masks_google_api_key() -> None:
    # Google API keys are exactly 39 chars ("AIza" + 35).
    sample = "key=AIzaSyD-abcdefghijklmnopqrstuvwx0123456 trailing"
    out = redact(sample)
    assert "AIzaSyD" not in out
    assert "[REDACTED_GOOGLE_API_KEY]" in out


def test_redact_masks_aws_access_key_ids() -> None:
    sample = "access=AKIAIOSFODNN7EXAMPLE temp=ASIAIOSFODNN7EXAMPLE"
    out = redact(sample)
    assert "AKIA" not in out
    assert "ASIA" not in out
    assert out.count("[REDACTED_AWS_KEY_ID]") == 2


def test_redact_masks_pem_private_key_block() -> None:
    sample = (
        "before\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA1234567890abcdef\n"
        "ABCDEF\n"
        "-----END RSA PRIVATE KEY-----\n"
        "after"
    )
    out = redact(sample)
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert "MIIEpAIBAA" not in out
    assert "[REDACTED_PRIVATE_KEY]" in out
    # Surrounding context is preserved.
    assert "before" in out
    assert "after" in out


# ---- B: artifact_path is now redacted in the Observations section --------


def test_report_observation_artifact_path_is_redacted() -> None:
    """If an artifact_path itself contains an email-like substring it should
    be masked in the Observations section (Evidence already does this)."""
    from datetime import UTC, datetime
    from pathlib import Path

    from app.db import session_scope
    from app.models import Observation, Scenario
    from app.reports import generate_markdown_report

    base_ts = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
    with session_scope() as session:
        scenario = Scenario(
            name="hardening_obs_path",
            target_service="example.com",
            hypothesis="hardening test",
            created_at=base_ts,
        )
        session.add(scenario)
        session.flush()
        sid = scenario.id
        # Synthetic artifact path with an email substring.
        bad_path = (
            "/home/me/scratch/scenario/before/"
            "20260511T120000Z_alice@example.com_snapshot.html"
        )
        session.add(
            Observation(
                scenario_id=sid,
                phase="before",
                observer_type="html",
                artifact_path=bad_path,
                note="",
                created_at=base_ts,
            )
        )

    with session_scope() as session:
        path = generate_markdown_report(session, sid, redact_secrets=True)
    text = Path(path).read_text(encoding="utf-8")
    obs_section = text.split("## Observations")[1].split("## Transitions")[0]
    assert "alice@example.com" not in obs_section
    assert "[REDACTED_EMAIL]" in obs_section


# ---- C: expanded extra_headers denylist -----------------------------------


def _scenario_for_api() -> int:
    from app.db import session_scope
    from app.models import Scenario

    with session_scope() as session:
        s = Scenario(name="hardening_api", target_service="httpbin", hypothesis="x")
        session.add(s)
        session.flush()
        return s.id


@pytest.mark.parametrize(
    "header_name",
    [
        "Cookie",
        "cookie",
        "X-Api-Key",
        "X-Auth-Token",
        "Proxy-Authorization",
        "X-Forwarded-User",
    ],
)
def test_extra_headers_denylist_rejects_credential_headers(
    monkeypatch: pytest.MonkeyPatch, header_name: str
) -> None:
    sid = _scenario_for_api()
    monkeypatch.setenv("SIL_API_DEMO_TOKEN", "x")
    from app.db import session_scope

    with session_scope() as session:
        with pytest.raises(ValueError, match="credential-bearing header"):
            fetch_api_template(
                session,
                sid,
                "before",
                template_name="self_account_demo",
                endpoint="/get",
                max_requests=1,
                extra_headers={header_name: "value-that-does-not-matter"},
                state=_RateState(),
            )


def test_extra_headers_allows_non_credential_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-auth headers like User-Agent are still permitted."""

    import json
    from typing import Any

    sid = _scenario_for_api()
    monkeypatch.setenv("SIL_API_DEMO_TOKEN", "secret")

    class _FakeResp:
        status_code = 200
        text = json.dumps({"ok": True})

    class _FakeSession:
        def __init__(self) -> None:
            self.last_headers: dict[str, Any] = {}

        def get(self, url: str, headers: dict[str, str], timeout: float) -> _FakeResp:
            self.last_headers = headers
            return _FakeResp()

    fake = _FakeSession()
    from app.db import session_scope

    with session_scope() as session:
        fetch_api_template(
            session,
            sid,
            "before",
            template_name="self_account_demo",
            endpoint="/get",
            max_requests=1,
            extra_headers={"User-Agent": "sil-test/1.0"},
            transport=fake,
            state=_RateState(),
        )
    assert fake.last_headers.get("User-Agent") == "sil-test/1.0"
    # Auth header still set by the template, not from extra_headers.
    assert fake.last_headers["Authorization"] == "Bearer secret"
