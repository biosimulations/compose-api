"""Environments and their versions (docs/plan-environment-versions.md).

An environment (``registry_env``, a prebuilt simulator's name) has numbered versions. Each version is one simulator
row, its definition and hash, through which its images and build runs already hang (docs/plan-environment-builds.md),
plus what it was made from. The environment's default version is the one a run that names none gets.
"""

import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase
from compose_api.simulation.models import EnvironmentVersion, VersionState


class ORMEnvironment(DeclarativeTableBase):
    __tablename__ = "environment"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # shared, prebuilt
    # use_alter: the two tables reference each other
    default_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("environment_version.id", use_alter=True, ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class ORMEnvironmentVersion(DeclarativeTableBase):
    __tablename__ = "environment_version"
    __table_args__ = (
        UniqueConstraint("environment", "number", name="uq_environment_version_number"),
        UniqueConstraint("environment", "simulator_id", name="uq_environment_version_simulator"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(ForeignKey("environment.name"), nullable=False, index=True)
    number: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    simulator_id: Mapped[int] = mapped_column(ForeignKey("simulator.id"), nullable=False, index=True)
    # prebuilt: the image, by digest
    image: Mapped[str | None] = mapped_column(Text, nullable=True)
    # shared: what it was made from, and (step 3) its lock, whose hash is its identity
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    origin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    lock: Mapped[str | None] = mapped_column(Text, nullable=True)
    lock_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # read from its image once built (step 4)
    installed: Mapped[str | None] = mapped_column(Text, nullable=True)
    interfaces: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    runtime_contract: Mapped[int] = mapped_column(nullable=False, server_default="1")
    created_by: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_environment_version(self) -> EnvironmentVersion:
        return EnvironmentVersion(
            database_id=self.id,
            environment=self.environment,
            number=self.number,
            state=VersionState(self.state),
            simulator_id=self.simulator_id,
            image=self.image,
            spec=self.spec,
            origin=self.origin,
            resolved_at=self.resolved_at,
            lock_sha256=self.lock_sha256,
            runtime_contract=self.runtime_contract,
            created_by=self.created_by,
            created_at=self.created_at,
            note=self.note,
        )
