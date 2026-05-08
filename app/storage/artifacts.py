"""Filesystem helpers for storing observation artifacts.

Layout:

    <artifacts_dir>/
        scenario_<id>_<slug>/
            before/
            after/
            delayed_after/

Each artifact is written with a UTC timestamp prefix so the natural sort order
matches the time order.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings


class ArtifactKind(str, Enum):
    MANUAL = "manual"
    SCREENSHOT = "screenshot"
    HTML = "html"
    JSON = "json"
    API = "api"


_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-") or "scenario"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def scenario_dir(
    scenario_id: int,
    scenario_name: str,
    phase: str,
    *,
    settings: Settings | None = None,
) -> Path:
    settings = settings or get_settings()
    base = settings.artifacts_dir / f"scenario_{scenario_id:04d}_{_slug(scenario_name)}" / phase
    base.mkdir(parents=True, exist_ok=True)
    return base


def _make_path(target_dir: Path, label: str, suffix: str) -> Path:
    name = f"{_timestamp()}_{_slug(label)}{suffix}"
    return target_dir / name


def save_text(target_dir: Path, label: str, content: str, suffix: str = ".txt") -> Path:
    path = _make_path(target_dir, label, suffix)
    path.write_text(content, encoding="utf-8")
    return path


def save_html(target_dir: Path, label: str, content: str) -> Path:
    return save_text(target_dir, label, content, suffix=".html")


def save_json(target_dir: Path, label: str, payload: Any) -> Path:
    path = _make_path(target_dir, label, ".json")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def copy_artifact(target_dir: Path, source: Path, label: str | None = None) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"Source artifact does not exist: {source}")
    suffix = source.suffix or ""
    label = label or source.stem
    path = _make_path(target_dir, label, suffix)
    shutil.copy2(source, path)
    return path
