"""Pack a scenario for Bug Bounty / QA submission or operator handoff.

The bundle is a single zip with this layout:

    <bundle>.zip
        manifest.json
        report.md
        artifacts/<original-relative-path>...

Design constraints:

- Artifacts are stored under their *relative* path inside the artifacts
  directory. Anything that resolves outside the scenario's artifact
  subtree is refused (no symlink / `..` escape).
- Files named like a Playwright `storage_state.json` are always refused.
  The export is for evidence, not for credentials.
- `report.md` is generated fresh by `generate_markdown_report`, honoring
  the redaction setting.
- `manifest.json` includes SHA-256 of every member, every observation /
  transition / diff / delayed-check row, and the scenario metadata. It
  does NOT include the bundle's own SHA-256 (the operator can compute
  that with `sha256sum` after the bundle is written).
- The bundle is refused if it would land inside the artifacts directory
  (that would recursively grow the next export).
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Scenario
from app.reports import generate_markdown_report

_FORBIDDEN_NAMES: tuple[str, ...] = ("storage_state.json", "storage-state.json")
BUNDLE_FORMAT_VERSION = 1


def _parse_diff_ids_for_manifest(raw: str) -> list[int]:
    """Mirror of `app.findings._parse_diff_ids` without a circular import risk."""
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    out: list[int] = []
    for item in loaded:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


class ExportSafetyError(RuntimeError):
    """Raised when an export would violate the safety rules above."""


@dataclass
class ExportResult:
    bundle_path: Path
    bundle_sha256: str
    files_count: int
    bundle_size: int
    redaction_applied: bool
    manifest_path_in_bundle: str = "manifest.json"
    report_path_in_bundle: str = "report.md"


def _sha256_of(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _fmt_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _scenario_root(settings: Settings, scenario: Scenario) -> Path:
    """Compute the canonical artifact subtree for a scenario.

    Mirrors the layout used by `app.storage.artifacts.scenario_dir` but
    here we only need the parent (without phase) so we can check that all
    of a scenario's artifacts live under it.
    """
    import re

    slug = re.sub(r"[^a-z0-9._-]+", "-", scenario.name.lower()).strip("-") or "scenario"
    return (settings.artifacts_dir / f"scenario_{scenario.id:04d}_{slug}").resolve()


def _ensure_inside(target: Path, parent: Path) -> Path:
    """Resolve `target`; raise if it does not sit under `parent`."""
    resolved = target.resolve()
    try:
        resolved.relative_to(parent)
    except ValueError as exc:
        raise ExportSafetyError(
            f"artifact path {target} escapes the scenario directory {parent}"
        ) from exc
    return resolved


def export_scenario(
    session: Session,
    scenario_id: int,
    *,
    output_path: Path | str | None = None,
    settings: Settings | None = None,
    redact_secrets: bool | None = None,
    force: bool = False,
) -> ExportResult:
    settings = settings or get_settings()
    settings.ensure_dirs()
    do_redact = settings.redact_by_default if redact_secrets is None else redact_secrets

    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise ValueError(f"Scenario id={scenario_id} not found.")

    scenario_root = _scenario_root(settings, scenario)
    artifacts_root = settings.artifacts_dir.resolve()

    timestamp = datetime.now(UTC)
    bundle_filename = (
        f"scenario_{scenario.id:04d}_export_{timestamp.strftime('%Y%m%dT%H%M%SZ')}.zip"
    )
    if output_path is None:
        out = (settings.reports_dir / bundle_filename).resolve()
    else:
        out = Path(output_path).resolve()
        if out.is_dir():
            out = out / bundle_filename

    out_parent = out.parent.resolve()
    try:
        out_parent.relative_to(artifacts_root)
    except ValueError:
        pass
    else:
        raise ExportSafetyError(
            f"refusing to write bundle inside the artifacts directory: {out}"
        )

    if out.exists() and not force:
        raise ExportSafetyError(
            f"refusing to overwrite existing bundle: {out} (pass force=True)"
        )

    # Build the report fresh; redaction is applied here.
    report_path = generate_markdown_report(
        session, scenario.id, settings=settings, redact_secrets=do_redact
    )

    # Inventory: every observation's artifact is included, plus diff images
    # written next to a screenshot artifact.
    inventory: list[tuple[Path, str]] = []  # (source_path, path_in_bundle)
    for obs in scenario.observations:
        if not obs.artifact_path:
            continue
        src = Path(obs.artifact_path)
        if src.name in _FORBIDDEN_NAMES:
            raise ExportSafetyError(
                f"refusing to include forbidden artifact name: {src.name}"
            )
        if not src.exists():
            continue
        resolved = _ensure_inside(src, scenario_root)
        rel = resolved.relative_to(scenario_root)
        inventory.append((resolved, f"artifacts/{rel.as_posix()}"))

    # Diff images that live next to an after artifact (Phase 2 screenshot diff).
    seen = {p for _, p in inventory}
    for obs in scenario.observations:
        if not obs.artifact_path:
            continue
        src = Path(obs.artifact_path)
        if not src.exists():
            continue
        sibling_dir = src.parent
        try:
            sibling_dir_resolved = _ensure_inside(sibling_dir, scenario_root)
        except ExportSafetyError:
            continue
        for cand in sibling_dir_resolved.glob("diff_*.png"):
            rel = cand.relative_to(scenario_root)
            in_bundle = f"artifacts/{rel.as_posix()}"
            if in_bundle in seen:
                continue
            inventory.append((cand, in_bundle))
            seen.add(in_bundle)

    manifest = _build_manifest(scenario, inventory, do_redact, timestamp)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
            zf.write(report_path, arcname="report.md")
            for src, in_bundle in inventory:
                zf.write(src, arcname=in_bundle)
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()

    bundle_sha, bundle_size = _sha256_of(out)
    files_count = 2 + len(inventory)  # manifest + report + artifacts
    return ExportResult(
        bundle_path=out,
        bundle_sha256=bundle_sha,
        files_count=files_count,
        bundle_size=bundle_size,
        redaction_applied=do_redact,
    )


def _build_manifest(
    scenario: Scenario,
    inventory: list[tuple[Path, str]],
    redaction_applied: bool,
    exported_at: datetime,
) -> dict:
    meta = scenario.metadata_row
    files: list[dict] = []
    for src, in_bundle in inventory:
        digest, size = _sha256_of(src)
        files.append(
            {
                "path_in_bundle": in_bundle,
                "original_path": str(src),
                "sha256": digest,
                "size": size,
            }
        )

    file_by_original = {entry["original_path"]: entry for entry in files}

    return {
        "format_version": BUNDLE_FORMAT_VERSION,
        "exported_at": _fmt_dt(exported_at),
        "redaction_applied": redaction_applied,
        "scenario": {
            "id": scenario.id,
            "name": scenario.name,
            "target_service": scenario.target_service,
            "hypothesis": scenario.hypothesis,
            "template": scenario.template,
            "status": scenario.status,
            "created_at": _fmt_dt(scenario.created_at),
        },
        "metadata": None
        if meta is None
        else {
            "scope_authorization": meta.scope_authorization,
            "test_data_used": meta.test_data_used,
            "expected_behavior": meta.expected_behavior,
            "actual_behavior": meta.actual_behavior,
            "security_impact": meta.security_impact,
            "limitations": meta.limitations,
            "recommended_fix": meta.recommended_fix,
            "updated_at": _fmt_dt(meta.updated_at),
        },
        "observations": [
            {
                "id": o.id,
                "phase": o.phase,
                "observer_type": o.observer_type,
                "artifact_path": o.artifact_path,
                "note": o.note,
                "created_at": _fmt_dt(o.created_at),
                "sha256": file_by_original.get(
                    str(Path(o.artifact_path).resolve()) if o.artifact_path else "",
                    {},
                ).get("sha256"),
            }
            for o in scenario.observations
        ],
        "transitions": [
            {
                "id": t.id,
                "transition_type": t.transition_type,
                "performed_by": t.performed_by,
                "note": t.note,
                "created_at": _fmt_dt(t.created_at),
            }
            for t in scenario.transitions
        ],
        "diffs": [
            {
                "id": d.id,
                "diff_type": d.diff_type,
                "severity_hint": d.severity_hint,
                "before_observation_id": d.before_observation_id,
                "after_observation_id": d.after_observation_id,
                "summary": d.summary,
                "created_at": _fmt_dt(d.created_at),
            }
            for d in scenario.diffs
        ],
        "findings": [
            {
                "id": f.id,
                "title": f.title,
                "description": f.description,
                "severity": f.severity,
                "status": f.status,
                "external_id": f.external_id,
                "diff_ids": _parse_diff_ids_for_manifest(f.diff_ids),
                "note": f.note,
                "bounty_amount": f.bounty_amount,
                "bounty_currency": f.bounty_currency,
                "created_at": _fmt_dt(f.created_at),
                "updated_at": _fmt_dt(f.updated_at),
                "closed_at": _fmt_dt(f.closed_at),
            }
            for f in scenario.findings
        ],
        "delayed_checks": [
            {
                "id": c.id,
                "run_after": _fmt_dt(c.run_after),
                "executed_at": _fmt_dt(c.executed_at),
                "note": c.note,
            }
            for c in scenario.delayed_checks
        ],
        "files": files,
    }
