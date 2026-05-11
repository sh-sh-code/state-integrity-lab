"""Tests for `sil scenario export` and `app.exporters.bundle.export_scenario`."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import app
from app.config import get_settings
from app.db import session_scope
from app.exporters import ExportSafetyError, export_scenario
from app.models import Observation, Scenario, ScenarioMetadata
from app.observer import record_html, record_screenshot
from app.storage.artifacts import scenario_dir


def _make_scenario_with_artifacts(name: str, tmp_path: Path) -> int:
    """Create a scenario + before/after HTML observations + one screenshot."""
    before_html = tmp_path / "before.html"
    before_html.write_text("<html>secret-roadmap-q4</html>", encoding="utf-8")
    after_html = tmp_path / "after.html"
    after_html.write_text("<html>still secret-roadmap-q4</html>", encoding="utf-8")
    shot = tmp_path / "shot.png"
    # 1x1 PNG.
    shot.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c63600100000005000178f6a8950000000049454e44ae42"
            "6082"
        )
    )

    with session_scope() as session:
        scenario = Scenario(
            name=name, target_service="example.com", hypothesis="hypothesis"
        )
        session.add(scenario)
        session.flush()
        sid = scenario.id
        meta = ScenarioMetadata(
            scenario_id=sid,
            scope_authorization="own account only",
            expected_behavior="deleted item must not persist",
            actual_behavior="persists after 5m",
        )
        session.add(meta)
        session.flush()

        record_html(session, sid, "before", source_path=before_html, note="initial")
        record_html(session, sid, "after", source_path=after_html, note="post-transition")
        record_screenshot(session, sid, "after", shot, note="after shot")
    return sid


def test_export_bundle_layout_and_manifest(tmp_path: Path) -> None:
    sid = _make_scenario_with_artifacts("exp_layout", tmp_path)
    with session_scope() as session:
        result = export_scenario(session, sid, redact_secrets=True)

    assert result.bundle_path.exists()
    assert result.bundle_size > 0
    assert result.files_count >= 4  # manifest + report + 3 artifacts

    with zipfile.ZipFile(result.bundle_path) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "report.md" in names
        artifact_entries = [n for n in names if n.startswith("artifacts/")]
        assert len(artifact_entries) >= 3

        manifest = json.loads(zf.read("manifest.json"))

    assert manifest["format_version"] == 1
    assert manifest["scenario"]["id"] == sid
    assert manifest["scenario"]["name"] == "exp_layout"
    assert manifest["metadata"]["scope_authorization"] == "own account only"
    assert len(manifest["observations"]) == 3
    assert len(manifest["files"]) >= 3

    # Every file entry's recorded sha256 must match the bytes in the zip.
    with zipfile.ZipFile(result.bundle_path) as zf:
        for entry in manifest["files"]:
            data = zf.read(entry["path_in_bundle"])
            assert hashlib.sha256(data).hexdigest() == entry["sha256"]
            assert len(data) == entry["size"]


def test_export_refuses_overwrite_without_force(tmp_path: Path) -> None:
    sid = _make_scenario_with_artifacts("exp_overwrite", tmp_path)
    target = tmp_path / "bundle.zip"
    with session_scope() as session:
        export_scenario(session, sid, output_path=target)
    with session_scope() as session:
        with pytest.raises(ExportSafetyError):
            export_scenario(session, sid, output_path=target)
    # With force=True it succeeds.
    with session_scope() as session:
        export_scenario(session, sid, output_path=target, force=True)


def test_export_refuses_artifact_outside_scenario_root(tmp_path: Path) -> None:
    """An artifact_path pointing outside the scenario subtree must be refused."""
    sid = _make_scenario_with_artifacts("exp_traversal", tmp_path)
    # Manually corrupt one observation's artifact_path to point at tmp_path
    # (which is outside artifacts_dir).
    stray = tmp_path / "stray.html"
    stray.write_text("data", encoding="utf-8")
    with session_scope() as session:
        scenario = session.get(Scenario, sid)
        assert scenario is not None
        scenario.observations[0].artifact_path = str(stray)
    with session_scope() as session:
        with pytest.raises(ExportSafetyError):
            export_scenario(session, sid, output_path=tmp_path / "bundle.zip")


def test_export_refuses_forbidden_filename(tmp_path: Path) -> None:
    """`storage_state.json` must never end up in the bundle."""
    sid = _make_scenario_with_artifacts("exp_storage", tmp_path)
    # Inject a forged artifact with a forbidden name inside the scenario dir.
    target_dir = scenario_dir(sid, "exp_storage", "before")
    bad = target_dir / "storage_state.json"
    bad.write_text("{\"cookies\": []}", encoding="utf-8")
    with session_scope() as session:
        scenario = session.get(Scenario, sid)
        assert scenario is not None
        scenario.observations[0].artifact_path = str(bad)
    with session_scope() as session:
        with pytest.raises(ExportSafetyError):
            export_scenario(session, sid, output_path=tmp_path / "bundle.zip")


def test_export_refuses_output_inside_artifacts_dir(tmp_path: Path) -> None:
    """Writing the bundle under artifacts_dir would recurse on next export."""
    sid = _make_scenario_with_artifacts("exp_inside", tmp_path)
    settings = get_settings()
    bad_target = settings.artifacts_dir / "bundle.zip"
    with session_scope() as session:
        with pytest.raises(ExportSafetyError):
            export_scenario(session, sid, output_path=bad_target)


def test_export_report_md_is_redacted_by_default(tmp_path: Path) -> None:
    sid = _make_scenario_with_artifacts("exp_redact", tmp_path)
    with session_scope() as session:
        scenario = session.get(Scenario, sid)
        assert scenario is not None
        scenario.metadata_row.scope_authorization = (
            "Tested under alice@example.com only."
        )
    with session_scope() as session:
        result = export_scenario(session, sid, output_path=tmp_path / "b.zip")
    with zipfile.ZipFile(result.bundle_path) as zf:
        report = zf.read("report.md").decode("utf-8")
    assert "alice@example.com" not in report
    assert "[REDACTED_EMAIL]" in report


def test_cli_scenario_export(tmp_path: Path) -> None:
    sid = _make_scenario_with_artifacts("exp_cli", tmp_path)
    bundle = tmp_path / "cli.zip"
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "scenario",
            "export",
            "--scenario",
            str(sid),
            "--output",
            str(bundle),
        ],
    )
    assert r.exit_code == 0, r.stdout
    assert "wrote export bundle" in r.stdout
    assert "sha256" in r.stdout
    assert bundle.exists()


def test_cli_scenario_export_unknown_id(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "scenario",
            "export",
            "--scenario",
            "99999",
            "--output",
            str(tmp_path / "x.zip"),
        ],
    )
    assert r.exit_code != 0


def test_bundle_sha256_is_stable(tmp_path: Path) -> None:
    sid = _make_scenario_with_artifacts("exp_sha", tmp_path)
    with session_scope() as session:
        result = export_scenario(session, sid, output_path=tmp_path / "b.zip")
    # Recompute the sha by hand; it must match what the export reports.
    h = hashlib.sha256()
    with result.bundle_path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    assert h.hexdigest() == result.bundle_sha256
