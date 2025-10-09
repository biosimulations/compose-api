import datetime
import logging
from abc import ABC, abstractmethod

from sqlalchemy import Result, and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute
from typing_extensions import override

from compose_api.common.hpc.models import SlurmJob
from compose_api.db.tables_orm import (
    JobStatusDB,
    JobTypeDB,
    ORMHpcRun,
    ORMWorkerEvent,
)
from compose_api.simulation.models import (
    HpcRun,
    JobType,
    WorkerEvent,
)

logger = logging.getLogger(__name__)


class HPCDatabaseService(ABC):
    @abstractmethod
    async def insert_worker_event(self, worker_event: WorkerEvent, hpcrun_id: int) -> WorkerEvent:
        pass

    @abstractmethod
    async def list_worker_events(self, hpcrun_id: int, prev_sequence_number: int | None = None) -> list[WorkerEvent]:
        pass

    @abstractmethod
    async def insert_hpcrun(self, slurmjobid: int, job_type: JobType, ref_id: int, correlation_id: str) -> HpcRun:
        """
        :param slurmjobid: (`int`) slurm job id for the associated `job_type`.
        :param job_type: (`JobType`) job type to be run. Choose one of the following:
            `JobType.SIMULATION`
        :param ref_id: primary key of the object this HPC run is associated with (sim, etc.).
        """
        pass

    @abstractmethod
    async def get_hpcrun_by_ref(self, ref_id: int, job_type: JobType) -> HpcRun | None:
        pass

    @abstractmethod
    async def get_hpcrun_by_slurmjobid(self, slurmjobid: int) -> HpcRun | None:
        pass

    @abstractmethod
    async def get_hpcrun(self, hpcrun_id: int) -> HpcRun | None:
        pass

    @abstractmethod
    async def get_hpcrun_id_by_correlation_id(self, correlation_id: str) -> int | None:
        pass

    @abstractmethod
    async def get_hpcrun_id_by_simulator_id(self, simulator_id: int) -> int | None:
        pass

    @abstractmethod
    async def delete_hpcrun(self, hpcrun_id: int) -> None:
        pass

    @abstractmethod
    async def list_running_hpcruns(self) -> list[HpcRun]:
        """Return all HpcRun jobs with status RUNNING."""
        pass

    @abstractmethod
    async def update_hpcrun_status(self, hpcrun_id: int, new_slurm_job: SlurmJob) -> None:
        """Update the status of a given HpcRun job."""
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class HPCORMExecutor(HPCDatabaseService):
    async_session_maker: async_sessionmaker[AsyncSession]

    def __init__(self, async_session_maker: async_sessionmaker[AsyncSession]):
        self.async_session_maker = async_session_maker

    async def _get_orm_hpcrun(self, session: AsyncSession, hpcrun_id: int) -> ORMHpcRun | None:
        stmt1 = select(ORMHpcRun).where(ORMHpcRun.id == hpcrun_id).limit(1)
        result1: Result[tuple[ORMHpcRun]] = await session.execute(stmt1)
        orm_hpc_job: ORMHpcRun | None = result1.scalars().one_or_none()
        return orm_hpc_job

    async def _get_orm_hpcrun_by_slurmjobid(self, session: AsyncSession, slurmjobid: int) -> ORMHpcRun | None:
        stmt1 = select(ORMHpcRun).where(ORMHpcRun.slurmjobid == slurmjobid).limit(1)
        result1: Result[tuple[ORMHpcRun]] = await session.execute(stmt1)
        orm_hpc_job: ORMHpcRun | None = result1.scalars().one_or_none()
        return orm_hpc_job

    def _get_job_type_ref(self, job_type: JobType) -> InstrumentedAttribute[int | None]:
        match job_type:
            case JobType.SIMULATION:
                return ORMHpcRun.simulation_id
            case JobType.BUILD_CONTAINER:
                return ORMHpcRun.simulator_id

    async def _get_orm_hpcrun_by_ref(self, session: AsyncSession, ref_id: int, job_type: JobType) -> ORMHpcRun | None:
        reference = self._get_job_type_ref(job_type)
        stmt1 = select(ORMHpcRun).where(reference == ref_id).limit(1)
        result1: Result[tuple[ORMHpcRun]] = await session.execute(stmt1)
        orm_hpc_job: ORMHpcRun | None = result1.scalars().one_or_none()

        return orm_hpc_job

    @override
    async def insert_hpcrun(self, slurmjobid: int, job_type: JobType, ref_id: int, correlation_id: str) -> HpcRun:
        async with self.async_session_maker() as session, session.begin():
            simulation_key = ref_id if job_type == JobType.SIMULATION else None
            simulator_key = ref_id if job_type == JobType.BUILD_CONTAINER else None
            if simulator_key is None and simulation_key is None:
                raise ValueError(f"Simulation key and simulation key is None, with job type {job_type}")

            orm_hpc_run = ORMHpcRun(
                slurmjobid=slurmjobid,
                job_type=JobTypeDB.from_job_type(job_type),
                status=JobStatusDB.RUNNING,
                simulation_id=simulation_key,
                simulator_id=simulator_key,
                start_time=datetime.datetime.now(),
                correlation_id=correlation_id,
            )
            session.add(orm_hpc_run)
            await session.flush()
            return orm_hpc_run.to_hpc_run()

    @override
    async def get_hpcrun_by_slurmjobid(self, slurmjobid: int) -> HpcRun | None:
        async with self.async_session_maker() as session, session.begin():
            orm_hpc_job: ORMHpcRun | None = await self._get_orm_hpcrun_by_slurmjobid(session, slurmjobid=slurmjobid)
            if orm_hpc_job is None:
                return None
            return orm_hpc_job.to_hpc_run()

    @override
    async def get_hpcrun_by_ref(self, ref_id: int, job_type: JobType) -> HpcRun | None:
        async with self.async_session_maker() as session, session.begin():
            orm_hpc_job: ORMHpcRun | None = await self._get_orm_hpcrun_by_ref(session, ref_id=ref_id, job_type=job_type)
            if orm_hpc_job is None:
                return None
            return orm_hpc_job.to_hpc_run()

    @override
    async def get_hpcrun(self, hpcrun_id: int) -> HpcRun | None:
        async with self.async_session_maker() as session, session.begin():
            orm_hpc_job: ORMHpcRun | None = await self._get_orm_hpcrun(session, hpcrun_id=hpcrun_id)
            if orm_hpc_job is None:
                return None
            return orm_hpc_job.to_hpc_run()

    @override
    async def delete_hpcrun(self, hpcrun_id: int) -> None:
        async with self.async_session_maker() as session, session.begin():
            hpcrun: ORMHpcRun | None = await self._get_orm_hpcrun(session, hpcrun_id=hpcrun_id)
            if hpcrun is None:
                raise Exception(f"HpcRun with id {hpcrun_id} not found in the database")
            await session.delete(hpcrun)

    @override
    async def insert_worker_event(self, worker_event: WorkerEvent, hpcrun_id: int) -> WorkerEvent:
        async with self.async_session_maker() as session, session.begin():
            orm_worker_event = ORMWorkerEvent.from_worker_event(worker_event, hpcrun_id=hpcrun_id)
            session.add(orm_worker_event)
            await session.flush()  # Ensure the ORM object is inserted and has an ID

            new_worker_event = orm_worker_event.to_worker_event()
            return new_worker_event

    @override
    async def list_worker_events(self, hpcrun_id: int, prev_sequence_number: int | None = None) -> list[WorkerEvent]:
        async with self.async_session_maker() as session, session.begin():
            stmt = (
                select(
                    ORMWorkerEvent.mass,
                    ORMWorkerEvent.sequence_number,
                    ORMWorkerEvent.id,
                    ORMWorkerEvent.time,
                    ORMWorkerEvent.hpcrun_id,
                )
                .where(
                    and_(
                        ORMWorkerEvent.hpcrun_id == hpcrun_id,
                        ORMWorkerEvent.sequence_number > (prev_sequence_number or -1),
                    )
                )
                .order_by(ORMWorkerEvent.sequence_number)
            )
            result: Result[tuple[dict[str, float], int, int, float, int]] = await session.execute(stmt)
            orm_worker_events = result.all()

            worker_events: list[WorkerEvent] = []
            for orm_worker_event in orm_worker_events:
                worker_events.append(ORMWorkerEvent.from_query_results(orm_worker_event.tuple()))
            return worker_events

    @override
    async def list_running_hpcruns(self) -> list[HpcRun]:
        async with self.async_session_maker() as session:
            stmt = select(ORMHpcRun).where(ORMHpcRun.status == JobStatusDB.RUNNING)
            result: Result[tuple[ORMHpcRun]] = await session.execute(stmt)
            orm_hpcruns = result.scalars().all()
            return [orm_hpcrun.to_hpc_run() for orm_hpcrun in orm_hpcruns]

    @override
    async def update_hpcrun_status(self, hpcrun_id: int, new_slurm_job: SlurmJob) -> None:
        async with self.async_session_maker() as session, session.begin():
            orm_hpcrun: ORMHpcRun | None = await self._get_orm_hpcrun(session, hpcrun_id=hpcrun_id)
            if orm_hpcrun is None:
                raise Exception(f"HpcRun with id {hpcrun_id} not found in the database")
            orm_hpcrun.status = JobStatusDB(new_slurm_job.job_state.lower())
            if new_slurm_job.start_time is not None and new_slurm_job.start_time != orm_hpcrun.start_time:
                orm_hpcrun.start_time = datetime.datetime.fromisoformat(new_slurm_job.start_time)
            if new_slurm_job.end_time is not None and new_slurm_job.end_time != orm_hpcrun.end_time:
                orm_hpcrun.end_time = datetime.datetime.fromisoformat(new_slurm_job.end_time)
            await session.flush()

    @override
    async def get_hpcrun_id_by_correlation_id(self, correlation_id: str) -> int | None:
        return await self._get_hpcrun_id(correlation_id, ORMHpcRun.correlation_id)

    @override
    async def get_hpcrun_id_by_simulator_id(self, simulator_id: int) -> int | None:
        return await self._get_hpcrun_id(simulator_id, ORMHpcRun.simulator_id)

    async def _get_hpcrun_id(
        self, foreign_key: int | str, column: InstrumentedAttribute[int | str | None]
    ) -> int | None:
        async with self.async_session_maker() as session, session.begin():
            stmt = select(ORMHpcRun.id).where(column == foreign_key).limit(1)
            result: Result[tuple[int]] = await session.execute(stmt)
            orm_hpcrun_id: int | None = result.scalar_one_or_none()
            return orm_hpcrun_id

    @override
    async def close(self) -> None:
        pass
