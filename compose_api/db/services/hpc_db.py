import datetime
import logging
from abc import ABC, abstractmethod
from typing import override

from sqlalchemy import ColumnElement, Result, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute

from compose_api.common.hpc.models import SlurmJob
from compose_api.db.tables.hpc_tables import (
    TERMINAL_JOB_STATUSES,
    JobStatusDB,
    JobTypeDB,
    ORMHpcRun,
    ORMSubmission,
    ORMWorkerEvent,
)
from compose_api.db.tables.simulator_tables import ORMSimulation
from compose_api.observability.identity import trace_id_from_correlation
from compose_api.simulation.models import (
    ACTIVE_SUBMISSION_STATES,
    HpcRun,
    JobType,
    SimulationRequest,
    Submission,
    SubmissionState,
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
    async def insert_hpcrun(
        self,
        slurmjobid: int | None,
        job_type: JobType,
        ref_id: int,
        correlation_id: str,
        backend: str = "slurm",
        external_id: str | None = None,
    ) -> HpcRun:
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
    async def touch_submission(self, simulation_id: int) -> None:
        """Record that the task submitting ``simulation_id`` is still alive (its dispatch heartbeat)."""
        pass

    # -- the durable submission queue (docs/plan-durable-submission.md) -- #

    @abstractmethod
    async def claim_submissions(
        self, owner: str, lease_seconds: int, limit: int, exclude: frozenset[int] = frozenset()
    ) -> list[Submission]:
        """Lease up to ``limit`` due submissions to ``owner``, highest priority then oldest first. A row another worker
        holds (a live lease, or locked by its claim right now) is skipped, never waited on."""

    @abstractmethod
    async def renew_submission_lease(self, simulation_id: int, owner: str, lease_seconds: int) -> bool:
        """Extend ``owner``'s lease; False when it no longer holds the row (it expired and another worker took it)."""

    @abstractmethod
    async def set_submission_state(self, simulation_id: int, owner: str, state: SubmissionState) -> bool:
        """Move the submission ``owner`` holds to ``state``; False when it no longer holds it."""

    @abstractmethod
    async def retry_submission(self, simulation_id: int, owner: str, error: str, delay_seconds: int) -> None:
        """Count a failed attempt, keep its error, and release the row until ``delay_seconds`` from now."""

    @abstractmethod
    async def release_submission(self, simulation_id: int, owner: str) -> None:
        """Give the row back at once (a worker shutting down), so another can claim it without waiting out the lease."""

    @abstractmethod
    async def complete_submission(
        self, simulation_id: int, owner: str, slurmjobid: int, correlation_id: str
    ) -> HpcRun | None:
        """Record the SLURM job: the run and the move to ``submitted``, in one transaction. None (and nothing written)
        when ``owner`` no longer holds the row."""

    @abstractmethod
    async def get_submission(self, simulation_id: int) -> Submission | None:
        pass

    @abstractmethod
    async def list_stale_submissions(self, stale_seconds: int) -> list[int]:
        """Simulations with no run whose dispatch heartbeat (or creation, before any) is over ``stale_seconds`` old."""
        pass

    @abstractmethod
    async def fail_submission(self, simulation_id: int, reason: str) -> HpcRun | None:
        """Record a submission that never reached SLURM as a FAILED run with ``reason``, unless it has a run already
        (then None): the run was submitted after all, or another caller failed it first."""
        pass

    @abstractmethod
    async def get_hpcruns_by_refs(self, ref_ids: list[int], job_type: JobType) -> list[HpcRun]:
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
    async def list_unfinished_hpcruns(self) -> list[HpcRun]:
        """Return every HpcRun that has not reached a terminal status."""
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
        # the newest run of that type: a simulation's runs carry its simulator's id too, and a build may be retried
        reference = self._get_job_type_ref(job_type)
        stmt1 = (
            select(ORMHpcRun)
            .where(reference == ref_id, ORMHpcRun.job_type == JobTypeDB.from_job_type(job_type))
            .order_by(ORMHpcRun.id.desc())
            .limit(1)
        )
        result1: Result[tuple[ORMHpcRun]] = await session.execute(stmt1)
        orm_hpc_job: ORMHpcRun | None = result1.scalars().one_or_none()

        return orm_hpc_job

    @override
    async def insert_hpcrun(
        self,
        slurmjobid: int | None,
        job_type: JobType,
        ref_id: int,
        correlation_id: str,
        backend: str = "slurm",
        external_id: str | None = None,
    ) -> HpcRun:
        async with self.async_session_maker() as session, session.begin():
            orm_hpc_run = _new_hpcrun(slurmjobid, job_type, ref_id, correlation_id, backend, external_id)
            session.add(orm_hpc_run)
            await session.flush()
            return orm_hpc_run.to_hpc_run()

    @override
    async def claim_submissions(
        self, owner: str, lease_seconds: int, limit: int, exclude: frozenset[int] = frozenset()
    ) -> list[Submission]:
        now = func.localtimestamp()
        due = (
            select(ORMSubmission.simulation_id)
            .where(
                ORMSubmission.state.in_([s.value for s in ACTIVE_SUBMISSION_STATES]),
                ORMSubmission.next_attempt_at <= now,
                or_(ORMSubmission.lease_expires_at.is_(None), ORMSubmission.lease_expires_at < now),
            )
            .order_by(ORMSubmission.priority.desc(), ORMSubmission.created_at, ORMSubmission.simulation_id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if exclude:
            due = due.where(ORMSubmission.simulation_id.not_in(exclude))
        async with self.async_session_maker() as session, session.begin():
            ids = list((await session.execute(due)).scalars().all())
            if not ids:
                return []
            await session.execute(
                update(ORMSubmission)
                .where(ORMSubmission.simulation_id.in_(ids))
                .values(lease_owner=owner, lease_expires_at=_seconds_from_now(lease_seconds), updated_at=now)
            )
            rows = await session.execute(
                select(ORMSubmission, ORMSimulation.experiment_id, ORMSimulation.simulator_id)
                .join(ORMSimulation, ORMSimulation.id == ORMSubmission.simulation_id)
                .where(ORMSubmission.simulation_id.in_(ids))
            )
            by_id = {row[0].simulation_id: _submission(*row) for row in rows.all()}
            return [by_id[i] for i in ids if i in by_id]

    @override
    async def renew_submission_lease(self, simulation_id: int, owner: str, lease_seconds: int) -> bool:
        return await self._update_held(simulation_id, owner, lease_expires_at=_seconds_from_now(lease_seconds))

    @override
    async def set_submission_state(self, simulation_id: int, owner: str, state: SubmissionState) -> bool:
        return await self._update_held(simulation_id, owner, state=state.value)

    @override
    async def retry_submission(self, simulation_id: int, owner: str, error: str, delay_seconds: int) -> None:
        await self._update_held(
            simulation_id,
            owner,
            attempts=ORMSubmission.attempts + 1,
            last_error=error,
            next_attempt_at=_seconds_from_now(delay_seconds),
            lease_owner=None,
            lease_expires_at=None,
        )

    @override
    async def release_submission(self, simulation_id: int, owner: str) -> None:
        await self._update_held(simulation_id, owner, lease_owner=None, lease_expires_at=None)

    async def _update_held(self, simulation_id: int, owner: str, **values: object) -> bool:
        async with self.async_session_maker() as session, session.begin():
            result = await session.execute(
                update(ORMSubmission)
                .where(ORMSubmission.simulation_id == simulation_id, ORMSubmission.lease_owner == owner)
                .values(updated_at=func.localtimestamp(), **values)
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    @override
    async def complete_submission(
        self, simulation_id: int, owner: str, slurmjobid: int, correlation_id: str
    ) -> HpcRun | None:
        async with self.async_session_maker() as session, session.begin():
            held = await session.execute(
                select(ORMSubmission.simulation_id)
                .where(ORMSubmission.simulation_id == simulation_id, ORMSubmission.lease_owner == owner)
                .with_for_update()
            )
            if held.first() is None:
                return None
            orm_hpc_run = _new_hpcrun(
                slurmjobid=slurmjobid,
                job_type=JobType.SIMULATION,
                ref_id=simulation_id,
                correlation_id=correlation_id,
                backend="slurm",
                external_id=None,
            )
            session.add(orm_hpc_run)
            await session.execute(
                update(ORMSubmission)
                .where(ORMSubmission.simulation_id == simulation_id)
                .values(
                    state=SubmissionState.SUBMITTED.value,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=func.localtimestamp(),
                )
            )
            await session.flush()
            return orm_hpc_run.to_hpc_run()

    @override
    async def get_submission(self, simulation_id: int) -> Submission | None:
        async with self.async_session_maker() as session:
            row = (
                await session.execute(
                    select(ORMSubmission, ORMSimulation.experiment_id, ORMSimulation.simulator_id)
                    .join(ORMSimulation, ORMSimulation.id == ORMSubmission.simulation_id)
                    .where(ORMSubmission.simulation_id == simulation_id)
                )
            ).first()
            return None if row is None else _submission(*row)

    @override
    async def touch_submission(self, simulation_id: int) -> None:
        async with self.async_session_maker() as session, session.begin():
            await session.execute(
                update(ORMSimulation)
                .where(ORMSimulation.id == simulation_id)
                .values(dispatch_heartbeat_at=func.localtimestamp())
            )

    @override
    async def list_stale_submissions(self, stale_seconds: int) -> list[int]:
        has_run = (
            select(ORMHpcRun.id)
            .where(ORMHpcRun.simulation_id == ORMSimulation.id, ORMHpcRun.job_type == JobTypeDB.SIMULATION)
            .exists()
        )
        # Both columns are TIMESTAMP WITHOUT TIME ZONE in the session's zone (created_at defaults to now()), so the
        # cutoff is too.
        last_seen = func.coalesce(ORMSimulation.dispatch_heartbeat_at, ORMSimulation.created_at)
        cutoff = func.localtimestamp() - func.make_interval(0, 0, 0, 0, 0, 0, stale_seconds)
        # A queued run belongs to the submission worker, which resumes it after a restart instead (its lease)
        queued = (
            select(ORMSubmission.simulation_id)
            .where(
                ORMSubmission.simulation_id == ORMSimulation.id,
                ORMSubmission.state.in_([s.value for s in ACTIVE_SUBMISSION_STATES]),
            )
            .exists()
        )
        stmt = select(ORMSimulation.id).where(~has_run, ~queued, last_seen < cutoff).order_by(ORMSimulation.id)
        async with self.async_session_maker() as session:
            return list((await session.execute(stmt)).scalars().all())

    @override
    async def fail_submission(self, simulation_id: int, reason: str) -> HpcRun | None:
        async with self.async_session_maker() as session, session.begin():
            # Lock the simulation so the submitting task and the monitor cannot both record a run for it.
            await session.execute(select(ORMSimulation.id).where(ORMSimulation.id == simulation_id).with_for_update())
            existing = await session.execute(
                select(ORMHpcRun.id).where(
                    ORMHpcRun.simulation_id == simulation_id, ORMHpcRun.job_type == JobTypeDB.SIMULATION
                )
            )
            if existing.first() is not None:
                return None
            await session.execute(
                update(ORMSubmission)
                .where(ORMSubmission.simulation_id == simulation_id)
                .values(
                    state=SubmissionState.FAILED.value,
                    last_error=reason,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=func.localtimestamp(),
                )
            )
            now = datetime.datetime.now()
            orm_hpc_run = ORMHpcRun(
                slurmjobid=None,
                job_type=JobTypeDB.SIMULATION,
                status=JobStatusDB.FAILED,
                simulation_id=simulation_id,
                start_time=now,
                end_time=now,
                error_message=reason,
                # Unique per simulation (one failure at most, under the lock); no trace id, so no events to ingest.
                correlation_id=f"submission-failed-{simulation_id}",
            )
            session.add(orm_hpc_run)
            await session.flush()
            return orm_hpc_run.to_hpc_run()

    @override
    async def get_hpcruns_by_refs(self, ref_ids: list[int], job_type: JobType) -> list[HpcRun]:
        async with self.async_session_maker() as session, session.begin():
            run_type = self._get_job_type_ref(job_type)
            stmt = select(ORMHpcRun).where(run_type.in_(ref_ids))
            result: Result[tuple[ORMHpcRun]] = await session.execute(stmt)
            orm_hpcruns = result.scalars().all()
            return [orm_hpcrun.to_hpc_run() for orm_hpcrun in orm_hpcruns]

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
    async def list_unfinished_hpcruns(self) -> list[HpcRun]:
        async with self.async_session_maker() as session:
            stmt = select(ORMHpcRun).where(ORMHpcRun.status.not_in(TERMINAL_JOB_STATUSES))
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


def _new_hpcrun(
    slurmjobid: int | None,
    job_type: JobType,
    ref_id: int,
    correlation_id: str,
    backend: str = "slurm",
    external_id: str | None = None,
) -> ORMHpcRun:
    simulation_key = ref_id if job_type == JobType.SIMULATION else None
    simulator_key = ref_id if job_type == JobType.BUILD_CONTAINER else None
    if simulator_key is None and simulation_key is None:
        raise ValueError(f"Simulation key and simulation key is None, with job type {job_type}")
    return ORMHpcRun(
        slurmjobid=slurmjobid,
        backend=backend,
        external_id=external_id if external_id is not None else (str(slurmjobid) if slurmjobid else None),
        job_type=JobTypeDB.from_job_type(job_type),
        status=JobStatusDB.RUNNING,
        simulation_id=simulation_key,
        simulator_id=simulator_key,
        start_time=datetime.datetime.now(),
        correlation_id=correlation_id,
        trace_id=trace_id_from_correlation(correlation_id),
    )


def _seconds_from_now(seconds: int) -> ColumnElement[datetime.datetime]:
    # localtimestamp, as created_at and the heartbeat are: TIMESTAMP WITHOUT TIME ZONE in the session's zone
    return func.localtimestamp() + func.make_interval(0, 0, 0, 0, 0, 0, seconds)


def _submission(row: ORMSubmission, experiment_id: str, simulator_id: int) -> Submission:
    return Submission(
        simulation_id=row.simulation_id,
        experiment_id=experiment_id,
        simulator_id=simulator_id,
        state=SubmissionState(row.state),
        queue=row.queue,
        priority=row.priority,
        requested_by=row.requested_by,
        request=SimulationRequest.model_validate(row.request),
        staged_on_store=row.staged_on_store,
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
    )
