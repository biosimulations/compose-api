"""Comparisons of one SED-ML task run on several solvers (docs/plan-sedml.md, phase 3)."""

import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase


class ORMComparison(DeclarativeTableBase):
    __tablename__ = "comparison"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    name: Mapped[str] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(nullable=False)  # upload:<file>, biomodels:<id>, biosimulations:<project>
    sedml: Mapped[str] = mapped_column(nullable=False)  # the SED-ML file in the archive
    task: Mapped[str] = mapped_column(nullable=False)
    # tolerances, and each report's file and labels (where the members' CSVs are)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="running")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # a suite run's comparison (compose_api/sedml/suites.py): the suite and the run's number
    collection: Mapped[str | None] = mapped_column(nullable=True, index=True)
    suite_run: Mapped[int | None] = mapped_column(nullable=True)


class ORMComparisonMember(DeclarativeTableBase):
    __tablename__ = "comparison_member"
    __table_args__ = (UniqueConstraint("comparison_id", "solver", name="uq_comparison_member_solver"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(
        ForeignKey("comparison.id", ondelete="CASCADE"), nullable=False, index=True
    )
    simulation_id: Mapped[int] = mapped_column(
        ForeignKey("simulation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    solver: Mapped[str] = mapped_column(nullable=False)


class ORMComparisonReference(DeclarativeTableBase):
    """Results a comparison's runs are measured against, not among (docs/plan-sedml.md, D7): the original run's reports
    from biosimulations.org, or a `reports.h5` shipped in the archive. `reports`: `{report id: {label: series}}`."""

    __tablename__ = "comparison_reference"
    __table_args__ = (UniqueConstraint("comparison_id", "origin", name="uq_comparison_reference_origin"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(
        ForeignKey("comparison.id", ondelete="CASCADE"), nullable=False, index=True
    )
    origin: Mapped[str] = mapped_column(nullable=False)  # biosimulations:<run>, archive
    reports: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ORMSuiteRun(DeclarativeTableBase):
    """One run of a suite: its number within the suite, and the sources that could not be submitted, with why."""

    __tablename__ = "suite_run"
    __table_args__ = (UniqueConstraint("collection", "number", name="uq_suite_run_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    collection: Mapped[str] = mapped_column(nullable=False, index=True)
    number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="submitting")
    failures: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Its progress, so a restart resumes it (docs/plan-durable-submission.md, Q4): the sources to submit, the next one,
    # and the submission worker holding it while it is `submitting`.
    sources: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    next_source: Mapped[int] = mapped_column(nullable=False, server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(nullable=True)
    lease_expires_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)


class ORMVerification(DeclarativeTableBase):
    """A request to biosim's /verify API about one comparison (docs/plan-verify-oracle.md, V2): the archive the
    comparison ran, sent to BioSimulators' simulators, polled until it finishes, and its output kept here (biosim's
    workflow history is not kept forever). The submission worker drives it through `requested -> submitted ->
    completed | failed`, under a lease like a submission."""

    __tablename__ = "verification"
    __table_args__ = (Index("ix_verification_due", "state", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(
        ForeignKey("comparison.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default="omex")  # omex | runs
    simulators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="requested")
    workflow_id: Mapped[str | None] = mapped_column(nullable=True)
    workflow_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)  # biosim's VerifyWorkflowOutput
    verify_close: Mapped[bool | None] = mapped_column(nullable=True)  # BioSimulators' simulators agree
    attempts: Mapped[int] = mapped_column(nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(nullable=False, server_default=func.localtimestamp())
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(nullable=True)
    lease_expires_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(nullable=False, server_default=func.localtimestamp())
    updated_at: Mapped[datetime.datetime] = mapped_column(nullable=False, server_default=func.localtimestamp())
