import datetime
import enum
import logging
from typing import Optional

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase
from compose_api.simulation.models import (
    HpcRun,
    JobStatus,
    JobType,
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


class ORMHpcRun(DeclarativeTableBase):
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


class ORMWorkerEvent(DeclarativeTableBase):
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
