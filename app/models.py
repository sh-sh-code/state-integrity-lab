"""SQLAlchemy ORM models for State Integrity Lab."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


SCENARIO_TEMPLATES = (
    "connector_revoke_persistence",
    "project_knowledge_deletion",
    "team_permission_downgrade",
    "api_key_rotation_persistence",
    "export_after_deletion",
    "delayed_cache_inconsistency",
)

SCENARIO_STATUSES = ("draft", "in_progress", "blocked", "done")
OBSERVATION_PHASES = ("before", "after", "delayed_after")
OBSERVER_TYPES = ("manual", "screenshot", "html", "json", "api")
TRANSITION_PERFORMED_BY = ("human", "automated")
DIFF_TYPES = ("text", "json", "screenshot", "manual")
SEVERITY_HINTS = ("info", "low", "medium", "high", "needs_review")


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    target_service: Mapped[str] = mapped_column(String(255))
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    observations: Mapped[list[Observation]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )
    transitions: Mapped[list[Transition]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )
    diffs: Mapped[list[DiffResult]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )
    reports: Mapped[list[Report]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )
    delayed_checks: Mapped[list[DelayedCheck]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    phase: Mapped[str] = mapped_column(String(32))
    observer_type: Mapped[str] = mapped_column(String(32))
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    scenario: Mapped[Scenario] = relationship(back_populates="observations")


class Transition(Base):
    __tablename__ = "transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    transition_type: Mapped[str] = mapped_column(String(64))
    performed_by: Mapped[str] = mapped_column(String(32), default="human")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    scenario: Mapped[Scenario] = relationship(back_populates="transitions")


class DiffResult(Base):
    __tablename__ = "diff_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    before_observation_id: Mapped[int] = mapped_column(ForeignKey("observations.id"))
    after_observation_id: Mapped[int] = mapped_column(ForeignKey("observations.id"))
    diff_type: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text, default="")
    severity_hint: Mapped[str] = mapped_column(String(32), default="info")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    scenario: Mapped[Scenario] = relationship(back_populates="diffs")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    markdown_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    scenario: Mapped[Scenario] = relationship(back_populates="reports")


class DelayedCheck(Base):
    """Phase 2 will execute these; Phase 1 only records them."""

    __tablename__ = "delayed_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, default="")
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    scenario: Mapped[Scenario] = relationship(back_populates="delayed_checks")
