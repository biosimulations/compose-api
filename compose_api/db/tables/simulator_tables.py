import datetime
import logging

from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr
from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase, package_table_name
from compose_api.simulation.models import (
    ContainerEngine,
    DownloadedContainerImage,
    SimulatorVersion,
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
