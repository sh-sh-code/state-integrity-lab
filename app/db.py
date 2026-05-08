"""Database engine and session helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.models import Base

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker[Session]] = None


def _build_url(db_path: Path) -> str:
    return f"sqlite:///{db_path}"


def init_engine(settings: Optional[Settings] = None) -> Engine:
    """Build (or rebuild) the global engine and session factory."""
    global _engine, _SessionLocal
    settings = settings or get_settings()
    settings.ensure_dirs()
    _engine = create_engine(_build_url(settings.db_path), future=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        return init_engine()
    return _engine


def init_db(settings: Optional[Settings] = None) -> Engine:
    """Create the schema if missing. Idempotent."""
    engine = init_engine(settings)
    Base.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
