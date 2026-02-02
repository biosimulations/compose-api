import datetime
import logging

from pbest.utils.input_types import ContainerizationFileRepr
from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase, package_table_name
from compose_api.simulation.models import (
    SimulatorVersion,
)

logger = logging.getLogger(__name__)


class ORMSimulator(DeclarativeTableBase):
    __tablename__ = "simulator"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    singularity_def: Mapped[str] = mapped_column(nullable=False)
    singularity_def_hash: Mapped[str] = mapped_column(nullable=False)

    def to_simulator_version(self) -> SimulatorVersion:
        return SimulatorVersion(
            database_id=self.id,
            created_at=self.created_at,
            singularity_def=ContainerizationFileRepr(representation=self.singularity_def),
            singularity_def_hash=self.singularity_def_hash,
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
