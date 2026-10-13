"""Comparisons of one SED-ML task run on several solvers (docs/plan-sedml.md, phase 3)."""

import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint, func, text
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
