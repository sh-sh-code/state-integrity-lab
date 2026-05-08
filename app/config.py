"""Configuration loader for State Integrity Lab.

Reads from environment variables (optionally via a local `.env` file) and
exposes a single immutable `Settings` instance.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is optional at runtime.
    load_dotenv = None  # type: ignore[assignment]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    if load_dotenv is None:
        return
    env_path = _project_root() / ".env"
    if env_path.exists():
        load_dotenv(env_path)


_load_env_file()


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: Path
    artifacts_dir: Path
    reports_dir: Path
    redact_by_default: bool

    @classmethod
    def load(cls) -> Settings:
        root = _project_root()
        db_path = Path(os.getenv("SIL_DB_PATH", str(root / "state_integrity_lab.sqlite3"))).resolve()
        artifacts_dir = Path(os.getenv("SIL_ARTIFACTS_DIR", str(root / "artifacts"))).resolve()
        reports_dir = Path(os.getenv("SIL_REPORTS_DIR", str(root / "reports"))).resolve()
        redact = _bool_env("SIL_REDACT_BY_DEFAULT", True)
        return cls(
            db_path=db_path,
            artifacts_dir=artifacts_dir,
            reports_dir=reports_dir,
            redact_by_default=redact,
        )

    def ensure_dirs(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings.load()
