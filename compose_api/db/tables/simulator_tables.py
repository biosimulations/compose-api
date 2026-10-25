import datetime
import logging

from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr
from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase, package_table_name
from compose_api.db.tables.environment_tables import ORMEnvironmentVersion
from compose_api.simulation.models import (
    ContainerEngine,
    DownloadedContainerImage,
    EnvironmentImage,
    ImageKind,
    SimulationAccess,
    SimulatorVersion,
    Visibility,
)

logger = logging.getLogger(__name__)


class ORMDownloadedContainers(DeclarativeTableBase):
    __tablename__ = "downloaded_containers"
    id: Mapped[int] = mapped_column(primary_key=True)
    downloaded_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    source_url: Mapped[str] = mapped_column(nullable=False)
    image_name_and_tag: Mapped[str] = mapped_column(nullable=False)
    simulator_id: Mapped[int] = mapped_column(ForeignKey("simulator.id"), nullable=False, index=True)

    def to_downloaded_container_image(self, simulator: SimulatorVersion) -> DownloadedContainerImage:
        return DownloadedContainerImage(
            container_def=simulator.container_def,
            container_def_hash=simulator.container_def_hash,
            database_id=self.id,
            downloaded_at=self.downloaded_at,
            source_url=self.source_url,
            image_name_and_tag=self.image_name_and_tag,
            packages=None,
        )


class ORMSimulator(DeclarativeTableBase):
    __tablename__ = "simulator"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    container_def: Mapped[str] = mapped_column(nullable=False)
    container_def_hash: Mapped[str] = mapped_column(nullable=False)
    container_engine: Mapped[ContainerEngine] = mapped_column(nullable=False)

    def to_simulator_version(self) -> SimulatorVersion:
        return SimulatorVersion(
            database_id=self.id,
            created_at=self.created_at,
            container_def=ContainerizationFileRepr(
                representation=self.container_def,
                containerization_engine=ContainerizationEngine[self.container_engine.name],
            ),
            container_def_hash=self.container_def_hash,
            packages=None,
        )


class ORMEnvironmentImage(DeclarativeTableBase):
    """An image of a simulator's definition: built, pulled or adopted (docs/plan-environment-builds.md, E3).

    "Built" means an available row; a row whose file disappeared is marked unavailable and kept, so history survives.
    """

    __tablename__ = "environment_image"

    id: Mapped[int] = mapped_column(primary_key=True)
    simulator_id: Mapped[int] = mapped_column(ForeignKey("simulator.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    digest: Mapped[str | None] = mapped_column(nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    hpcrun_id: Mapped[int | None] = mapped_column(ForeignKey("hpcrun.id", ondelete="SET NULL"), nullable=True)
    available: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    verified_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)

    __table_args__ = (Index("ix_environment_image_lookup", "simulator_id", "kind", "available"),)

    def to_environment_image(self) -> EnvironmentImage:
        return EnvironmentImage(
            database_id=self.id,
            simulator_id=self.simulator_id,
            kind=ImageKind(self.kind),
            location=self.location,
            digest=self.digest,
            size_bytes=self.size_bytes,
            hpcrun_id=self.hpcrun_id,
            available=self.available,
            created_at=self.created_at,
            verified_at=self.verified_at,
        )


class ORMSimulatorToPackage(DeclarativeTableBase):
    __tablename__ = "simulator_to_package"

    id: Mapped[int] = mapped_column(primary_key=True)
    simulator_id: Mapped[int] = mapped_column(
        ForeignKey(ORMSimulator.__tablename__ + ".id"), nullable=False, index=True
    )
    package_id: Mapped[int] = mapped_column(ForeignKey(package_table_name + ".id"), nullable=False, index=True)


class ORMSimulation(DeclarativeTableBase):
    __tablename__ = "simulation"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    experiment_id: Mapped[str] = mapped_column(nullable=False, unique=True)
    simulator_id: Mapped[int] = mapped_column(ForeignKey("simulator.id"), nullable=False, index=True)
    # The environment version it ran in (docs/plan-environment-versions.md); none for runs recorded before versions.
    environment_version_id: Mapped[int | None] = mapped_column(
        ForeignKey(ORMEnvironmentVersion.__tablename__ + ".id"), nullable=True, index=True
    )

    # Who may read the simulation and everything it produced (docs/plan-observability.md O7). Its runs, events and
    # datasets carry no owner of their own: they inherit this through their foreign key.
    owner_sub: Mapped[str | None] = mapped_column(nullable=True, index=True)
    visibility: Mapped[str] = mapped_column(nullable=False, server_default=Visibility.PUBLIC.value)

    # Written periodically by the task submitting the simulation, until it reaches SLURM. A simulation with no run
    # whose heartbeat (or, before the first one, creation) is stale lost its task, e.g. to an API restart (#238).
    dispatch_heartbeat_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)

    # What the run is, for finding it again (docs/plan-sedml.md, phase 0). Labels are written by the service under
    # reserved keys (compose_api/simulation/labels.py); tags and the description are the submitter's, given at
    # submission. Both are queried by containment, through the GIN indexes below.
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default=text("'{}'::varchar[]"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_simulation_labels", "labels", postgresql_using="gin"),
        Index("ix_simulation_tags", "tags", postgresql_using="gin"),
    )

    def to_simulation_access(self) -> SimulationAccess:
        return SimulationAccess(
            simulation_id=self.id,
            experiment_id=self.experiment_id,
            owner_sub=self.owner_sub,
            visibility=Visibility(self.visibility),
        )
