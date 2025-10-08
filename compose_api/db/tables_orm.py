import datetime
import enum
import logging
import urllib.parse
from typing import Optional

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from compose_api.btools.bsander.bsandr_utils.input_types import ContainerizationFileRepr
from compose_api.simulation.models import (
    BiGraphEdge,
    BiGraphEdgeType,
    BiGraphPackage,
    BiGraphProcess,
    BiGraphStep,
    HpcRun,
    JobStatus,
    JobType,
    PackageType,
    SimulatorVersion,
    WorkerEvent,
)

logger = logging.getLogger(__name__)


class JobStatusDB(enum.Enum):
    WAITING = "waiting"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    def to_job_status(self) -> JobStatus:
        return JobStatus(self.value)


class JobTypeDB(enum.Enum):
    SIMULATION = "simulation"
    BUILD_CONTAINER = "build_container"

    def to_job_type(self) -> JobType:
        return JobType(self.value)

    @classmethod
    def from_job_type(cls, job_type: JobType) -> "JobTypeDB":
        return JobTypeDB(job_type.value)


class PackageTypeDB(enum.Enum):
    PYTHON = "python"
    CONDA = "conda"

    def to_package_type(self) -> "PackageType":
        return PackageType(self.value)

    @classmethod
    def from_package_type(cls, package_type: PackageType) -> "PackageTypeDB":
        return PackageTypeDB(package_type.value)


class BiGraphEdgeTypeDB(enum.Enum):
    PROCESS = "process"
    STEP = "step"

    def to_edge_type(self) -> "BiGraphEdgeType":
        return BiGraphEdgeType(self.value)

    @classmethod
    def from_edge_type(cls, edge_type: BiGraphEdgeType) -> "BiGraphEdgeTypeDB":
        return BiGraphEdgeTypeDB(edge_type.value)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class ORMSimulator(Base):
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


class ORMBiGraphEdge(Base):
    __tablename__ = "bigraph_edge"

    id: Mapped[int] = mapped_column(primary_key=True)
    inserted_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    module: Mapped[str] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    edge_type: Mapped[BiGraphEdgeTypeDB] = mapped_column(nullable=False)
    inputs: Mapped[str] = mapped_column(nullable=True)
    outputs: Mapped[str] = mapped_column(nullable=True)

    @classmethod
    def from_bigraph_edge(cls, edge: BiGraphEdge) -> "ORMBiGraphEdge":
        return cls(
            id=edge.database_id,
            module=edge.module,
            name=edge.name,
            edge_type=BiGraphEdgeTypeDB(edge.edge_type),
            input=edge.inputs,
            output=edge.outputs,
        )

    def to_bigraph_process(self) -> BiGraphProcess:
        if self.edge_type != BiGraphEdgeTypeDB.PROCESS:
            raise TypeError("Edge type must be BiGraphEdgeTypeDB Process")
        return BiGraphProcess(
            database_id=self.id,
            module=self.module,
            name=self.name,
            edge_type=self.edge_type.to_edge_type(),
            inputs=self.inputs,
            outputs=self.outputs,
        )

    def to_bigraph_step(self) -> BiGraphStep:
        if self.edge_type != BiGraphEdgeTypeDB.STEP:
            raise TypeError("Edge type must be BiGraphEdgeTypeDB Step")
        return BiGraphStep(
            database_id=self.id,
            module=self.module,
            name=self.name,
            edge_type=self.edge_type.to_edge_type(),
            inputs=self.inputs,
            outputs=self.outputs,
        )

    def to_bigraph_edge(self) -> BiGraphEdge:
        edge_type = self.edge_type.to_edge_type()
        match edge_type:
            case BiGraphEdgeType.PROCESS:
                return self.to_bigraph_process()
            case BiGraphEdgeType.STEP:
                return self.to_bigraph_step()
        raise ValueError(f"Edge type must be BiGraphEdgeTypeDB: {edge_type}")


class ORMPackage(Base):
    __tablename__ = "bigraph_package"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    source_uri: Mapped[str] = mapped_column(nullable=False)
    package_type: Mapped[PackageTypeDB] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)

    @classmethod
    def from_bigraph_package(cls, package: BiGraphPackage) -> "ORMPackage":
        return cls(
            id=package.database_id,
            source_uri=package.source_uri.geturl(),
            name=package.name,
            package_type=PackageTypeDB.from_package_type(package.package_type),
        )

    def to_bigraph_package(self, processes: list[BiGraphProcess], steps: list[BiGraphStep]) -> BiGraphPackage:
        uri = urllib.parse.urlparse(self.source_uri)
        return BiGraphPackage(
            database_id=self.id,
            package_type=PackageType(self.package_type.value),
            source_uri=uri,
            name=self.name,
            processes=processes,
            steps=steps,
        )


class ORMSimulatorToPackage(Base):
    __tablename__ = "simulator_to_package"

    id: Mapped[int] = mapped_column(primary_key=True)
    simulator_id: Mapped[int] = mapped_column(
        ForeignKey(ORMSimulator.__tablename__ + ".id"), nullable=False, index=True
    )
    package_id: Mapped[int] = mapped_column(ForeignKey(ORMPackage.__tablename__ + ".id"), nullable=False, index=True)


class ORMPackageToEdge(Base):
    __tablename__ = "packages_to_edge"

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey(ORMPackage.__tablename__ + ".id"), nullable=False, index=True)
    edge_id: Mapped[int] = mapped_column(ForeignKey(ORMBiGraphEdge.__tablename__ + ".id"), nullable=False, index=True)


class ORMHpcRun(Base):
    __tablename__ = "hpcrun"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    job_type: Mapped[JobTypeDB] = mapped_column(nullable=False)
    correlation_id: Mapped[str] = mapped_column(nullable=False, index=True, unique=True)
    slurmjobid: Mapped[int] = mapped_column(nullable=True)
    start_time: Mapped[Optional[datetime.datetime]] = mapped_column(nullable=True)
    end_time: Mapped[Optional[datetime.datetime]] = mapped_column(nullable=True)
    status: Mapped[JobStatusDB] = mapped_column(nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)

    simulation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("simulation.id"), nullable=True, index=True)
    simulator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("simulator.id"), nullable=True, index=True)

    def to_hpc_run(self) -> HpcRun:
        if self.simulation_id is None and self.simulator_id is None:
            raise RuntimeError("ORMHpcRun must have at least one job reference set.")
        return HpcRun(
            database_id=self.id,
            slurmjobid=self.slurmjobid,
            correlation_id=self.correlation_id,
            job_type=self.job_type.to_job_type(),
            sim_id=self.simulation_id,
            simulator_id=self.simulator_id,
            status=self.status.to_job_status(),
            error_message=self.error_message,
            start_time=str(self.start_time) if self.start_time else None,
            end_time=str(self.end_time) if self.end_time else None,
        )


class ORMSimulation(Base):
    __tablename__ = "simulation"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    experiment_id: Mapped[str] = mapped_column(nullable=False, unique=True)
    simulator_id: Mapped[int] = mapped_column(ForeignKey("simulator.id"), nullable=False, index=True)


class ORMWorkerEvent(Base):
    __tablename__ = "worker_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    correlation_id: Mapped[str] = mapped_column(
        ForeignKey(f"{ORMHpcRun.__tablename__}.correlation_id", ondelete="CASCADE")
    )
    sequence_number: Mapped[int] = mapped_column(nullable=False, index=True)
    mass: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    time: Mapped[float] = mapped_column(nullable=True)
    hpcrun_id: Mapped[int] = mapped_column(ForeignKey("hpcrun.id", ondelete="CASCADE"), nullable=False, index=True)

    @classmethod
    def from_worker_event(cls, worker_event: "WorkerEvent", hpcrun_id: int) -> "ORMWorkerEvent":
        return cls(
            # database_id=self.id,                 # populated in the database
            # created_at=str(self.created_at),     # populated in the database
            hpcrun_id=hpcrun_id,
            correlation_id=worker_event.correlation_id,
            sequence_number=worker_event.sequence_number,
            mass=worker_event.mass,
            time=worker_event.time,
        )

    def to_worker_event(self) -> WorkerEvent:
        return WorkerEvent(
            database_id=self.id,
            created_at=str(self.created_at),
            hpcrun_id=self.hpcrun_id,
            correlation_id=self.correlation_id,
            sequence_number=self.sequence_number,
            mass=self.mass,
            time=self.time,
        )

    @staticmethod
    def from_query_results(record: tuple[dict[str, float], int, int, float, int]) -> WorkerEvent:
        mass_data, sequence_number, record_id, event_time, hpcrun_id = record

        # ORMWorkerEvent.mass, ORMWorkerEvent.sequence_number, ORMWorkerEvent.id, ORMWorkerEvent.time
        return WorkerEvent(
            database_id=record_id,
            correlation_id="",
            sequence_number=sequence_number,
            mass=mass_data,
            time=event_time,
            hpcrun_id=hpcrun_id,
        )


async def create_db(async_engine: AsyncEngine) -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
