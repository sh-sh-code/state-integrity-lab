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
    metadata_row: Mapped[ScenarioMetadata | None] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
        uselist=False,
    )
    findings: Mapped[list[Finding]] = relationship(
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


SCENARIO_METADATA_FIELDS: tuple[str, ...] = (
    "scope_authorization",
    "test_data_used",
    "expected_behavior",
    "actual_behavior",
    "security_impact",
    "limitations",
    "recommended_fix",
)


FINDING_STATUSES: tuple[str, ...] = (
    "open",            # the operator has identified the issue locally
    "submitted",       # reported to the BB program / QA tracker
    "needs_more_info", # program / triager asked for more info
    "accepted",        # program accepted; severity / payout pending
    "fixed",           # operator confirmed the fix re-runs cleanly
    "wont_fix",        # program acknowledged but will not fix
    "duplicate",       # marked as duplicate by the program
)
FINDING_SEVERITIES: tuple[str, ...] = ("info", "low", "medium", "high", "critical")


class Finding(Base):
    """Operator-curated finding tied to a scenario.

    Distinct from `DiffResult` (which is an auto-generated diff). A finding
    is what the operator decides is worth tracking through triage, fix, and
    bounty award.
    """

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(32), default="medium")
    status: Mapped[str] = mapped_column(String(32), default="open")
    external_id: Mapped[str] = mapped_column(String(128), default="")
    diff_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of DiffResult.id
    note: Mapped[str] = mapped_column(Text, default="")
    bounty_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bounty_currency: Mapped[str] = mapped_column(String(8), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scenario: Mapped[Scenario] = relationship(back_populates="findings")


class ScenarioMetadata(Base):
    """Operator-supplied prose used to populate Bug Bounty / QA report sections."""

    __tablename__ = "scenario_metadata"

    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope_authorization: Mapped[str] = mapped_column(Text, default="")
    test_data_used: Mapped[str] = mapped_column(Text, default="")
    expected_behavior: Mapped[str] = mapped_column(Text, default="")
    actual_behavior: Mapped[str] = mapped_column(Text, default="")
    security_impact: Mapped[str] = mapped_column(Text, default="")
    limitations: Mapped[str] = mapped_column(Text, default="")
    recommended_fix: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    scenario: Mapped[Scenario] = relationship(back_populates="metadata_row")


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
