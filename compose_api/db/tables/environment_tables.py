"""Environments and their versions (docs/plan-environment-versions.md).

An environment has an id, its identity, and a name (``registry_env``, a prebuilt simulator's name) that may change:
everything that refers to an environment or a version refers to it by id, never by name. It has numbered versions.
Each version is one simulator row, its definition and hash, through which its images and build runs already hang
(docs/plan-environment-builds.md), plus what it was made from. The environment's default version is the one a run
that names none gets.
"""

import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from compose_api.db.db_utils import DeclarativeTableBase
from compose_api.simulation.models import EnvironmentVersion, EnvironmentVersionDetail, VersionState


class ORMEnvironment(DeclarativeTableBase):
    __tablename__ = "environment"

    id: Mapped[int] = mapped_column(primary_key=True)
    # what requests and pages call it; renaming it changes no reference (they hold the id)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # shared, prebuilt, mash-up
    # a mash-up's registry entries, sorted: its identity (docs/plan-environment-composition.md, D7.6); a declared
    # environment's are in environments.yaml, so none here
    entries: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # use_alter: the two tables reference each other
    default_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("environment_version.id", use_alter=True, ondelete="SET NULL"), nullable=True
    )
    # deployment: the deployment's own definition is adopted as the default (step 2); api: an administrator chose it
    default_source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="deployment")
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class ORMEnvironmentVersion(DeclarativeTableBase):
    __tablename__ = "environment_version"
    __table_args__ = (
        UniqueConstraint("environment_id", "number", name="uq_environment_version_number"),
        UniqueConstraint("environment_id", "simulator_id", name="uq_environment_version_simulator"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("environment.id"), nullable=False, index=True)
    # loaded with the version, for its current name
    env: Mapped[ORMEnvironment] = relationship(lazy="joined", foreign_keys=[environment_id])
    number: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    # None while a composed version is resolving: its definition, so its simulator, waits for its lock
    simulator_id: Mapped[int | None] = mapped_column(ForeignKey("simulator.id"), nullable=True, index=True)
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
    # why a version failed (a composed version's lock did not resolve: pixi's explanation)
    failure: Mapped[str | None] = mapped_column(Text, nullable=True)
    # the files that recreate it in other forms, by format: {"uv": {"pyproject.toml": ..., "uv.lock": ...}}
    exports: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # what the generic compliance checks found in its components, from its read-back (environments/compliance.py)
    findings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    def to_environment_version(self) -> EnvironmentVersion:
        return EnvironmentVersion(
            database_id=self.id,
            environment_id=self.environment_id,
            environment=self.env.name,
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
            failure=self.failure,
        )

    def to_environment_version_detail(self) -> EnvironmentVersionDetail:
        return EnvironmentVersionDetail(
            **self.to_environment_version().model_dump(),
            lock=self.lock,
            installed=self.installed,
            interfaces=self.interfaces,
            findings=self.findings,
        )


class ORMComplianceRun(DeclarativeTableBase):
    """One compliance case of a registry entry, run in an environment version (docs/plan-environment-composition.md,
    step 5): its run, and how it went."""

    __tablename__ = "compliance_run"
    __table_args__ = (UniqueConstraint("environment_version_id", "entry", "case", name="uq_compliance_run_case"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_version_id: Mapped[int] = mapped_column(
        ForeignKey("environment_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry: Mapped[str] = mapped_column(String(128), nullable=False)
    case: Mapped[str] = mapped_column(String(128), nullable=False)
    simulation_id: Mapped[int | None] = mapped_column(ForeignKey("simulation.id", ondelete="SET NULL"), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    failures: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
