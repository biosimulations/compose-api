import asyncio
import logging
from asyncio import Queue
from typing import TYPE_CHECKING, Protocol

from compose_api.common.hpc.models import SlurmJob
from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseService
from compose_api.observability.api_events import record_api_event
from compose_api.simulation.models import HpcRun, JobStatus

if TYPE_CHECKING:
    from compose_api.observability.ingest import EventIngester

logger = logging.getLogger(__name__)

_FAILED = frozenset({
    JobStatus.FAILED,
    JobStatus.CANCELLED,
    JobStatus.OUT_OF_MEMORY,
    JobStatus.TIMEOUT,
})


class BackendPoller(Protocol):
    """A backend other than SLURM (docs/plan-environment-builds.md, E2): the state of each of its jobs, by external
    id, as a SlurmJob (its `job_state` one of the JobStatus values, upper-case); a job it does not know is left out."""

    async def states(self, external_ids: list[str]) -> dict[str, SlurmJob]: ...


class JobMonitor:
    database_service: DatabaseService
    slurm_service: SlurmService
    internal_listeners: dict[int, Queue[HpcRun]] = {}
    pollers: dict[str, "BackendPoller"]
    _polling_task: asyncio.Task[None] | None = None
    _stop_event: asyncio.Event

    def __init__(
        self,
        database_service: DatabaseService,
        slurm_service: SlurmService,
        event_ingester: "EventIngester | None" = None,
    ):
        self.database_service = database_service
        self.slurm_service = slurm_service
        self.event_ingester = event_ingester
        self.pollers = {}
        self._stop_event = asyncio.Event()

    async def start_polling(self, interval_seconds: int = 30) -> None:
        if self._polling_task is not None and not self._polling_task.done():
            logger.warning("Polling task already running.")
            return
        self._stop_event.clear()
        self._polling_task = asyncio.create_task(self._polling_loop(interval_seconds))
        logger.info("Started job status polling task.")

    async def stop_polling(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._polling_task:
            await self._polling_task
            logger.info("Stopped job status polling task.")

    async def _polling_loop(self, interval_seconds: int) -> None:
        while not self._stop_event.is_set():
            try:
                await self.update_running_jobs()
            except Exception:
                logger.exception("Error during job polling")
            try:
                await self.fail_stale_submissions()
            except Exception:
                logger.exception("Error checking for stale submissions")
            if self.event_ingester is not None:
                try:
                    await self.event_ingester.ingest_once()
                except Exception:
                    logger.exception("Error during event ingest")
            await asyncio.sleep(interval_seconds)

    async def fail_stale_submissions(self) -> list[int]:
        """Fail every simulation whose submitting task is gone: no run, and no dispatch heartbeat for
        settings.submission_stale_seconds. Its task lived only in an API process that has since stopped (#238), so
        nothing would ever submit it. Returns the simulations failed."""
        stale_seconds = get_settings().submission_stale_seconds
        hpc_db = self.database_service.get_hpc_db()
        failed = []
        for simulation_id in await hpc_db.list_stale_submissions(stale_seconds):
            reason = (
                f"Submission abandoned: its task stopped reporting progress for over {stale_seconds} s before reaching"
                " SLURM (the API likely restarted); resubmit the simulation."
            )
            if await hpc_db.fail_submission(simulation_id, reason) is not None:
                logger.warning(f"Simulation {simulation_id}: {reason}")
                failed.append(simulation_id)
        return failed

    def register_backend(self, name: str, poller: "BackendPoller") -> None:
        """Poll runs whose backend is `name` with `poller` (docs/plan-environment-builds.md, E2); SLURM is built in."""
        self.pollers[name] = poller

    async def update_running_jobs(self) -> None:
        # Every run that has not reached a terminal status, not only the RUNNING ones: a
        # job seen as PENDING on one poll must still be polled on the next, or it is
        # abandoned in that state and never reaches COMPLETED.
        running_jobs = await self.database_service.get_hpc_db().list_unfinished_hpcruns()
        if not running_jobs:
            logger.debug("No unfinished jobs found for polling.")
            return
        observed = await self._observe(running_jobs)
        for hpc_run in running_jobs:
            slurm_job = observed.get(hpc_run.database_id)
            if not slurm_job or not slurm_job.job_state:
                continue
            try:
                new_status = JobStatus(slurm_job.job_state.lower())
                if new_status == hpc_run.status:
                    logger.debug(f"HpcRun {hpc_run.database_id} is still running with status {new_status}")
                    continue
                if hpc_run.status != new_status:
                    await self.database_service.get_hpc_db().update_hpcrun_status(
                        hpcrun_id=hpc_run.database_id, new_slurm_job=slurm_job
                    )
                    logger.info(f"Updated HpcRun {hpc_run.database_id} status to {new_status}")
                    await record_api_event(
                        self.database_service,
                        hpc_run,
                        f"{hpc_run.backend}.{new_status.value}",
                        {
                            "slurm_job_id": hpc_run.slurmjobid,
                            "external_id": hpc_run.external_id,
                            "previous": hpc_run.status.value if hpc_run.status else None,
                            "start_time": slurm_job.start_time,
                            "end_time": slurm_job.end_time,
                        },
                        level="error" if new_status in _FAILED else "info",
                    )
            except ValueError as e:
                logger.exception(
                    f"Error updating HpcRun {hpc_run.database_id} to status {slurm_job.job_state.lower()}."
                    f" Setting status to UNKNOWN.",
                    exc_info=e,
                )
                slurm_job.job_state = JobStatus.UNKNOWN.upper()
                await self.database_service.get_hpc_db().update_hpcrun_status(
                    hpcrun_id=hpc_run.database_id, new_slurm_job=slurm_job
                )
            except Exception:
                # One run's failed update (a database error) must not stop the others from being polled this pass.
                logger.exception(f"Error updating HpcRun {hpc_run.database_id}; polling the remaining runs.")
                continue

            if hpc_run.backend == "slurm" and slurm_job.job_id in self.internal_listeners:
                self.internal_listeners[slurm_job.job_id].put_nowait(hpc_run)

    async def _observe(self, runs: list[HpcRun]) -> dict[int, SlurmJob]:
        """Each run's job as its backend reports it, by run id: SLURM through squeue and sacct, any other backend
        through its registered poller by external id. A backend that fails to answer is skipped this pass."""
        observed: dict[int, SlurmJob] = {}
        slurm_runs = [r for r in runs if r.backend == "slurm" and r.slurmjobid]
        if slurm_runs:
            job_ids = [r.slurmjobid for r in slurm_runs if r.slurmjobid is not None]
            slurm_jobs_from_squeue = await self.slurm_service.get_job_status_squeue(job_ids)
            slurm_jobs_from_sacct = await self.slurm_service.get_job_status_sacct(job_ids)
            slurm_job_map = {job.job_id: job for job in slurm_jobs_from_squeue}
            slurm_job_map.update({job.job_id: job for job in slurm_jobs_from_sacct})
            for r in slurm_runs:
                if r.slurmjobid in slurm_job_map:
                    observed[r.database_id] = slurm_job_map[r.slurmjobid]
        for backend, poller in self.pollers.items():
            mine = [r for r in runs if r.backend == backend and r.external_id]
            if not mine:
                continue
            try:
                states = await poller.states([r.external_id for r in mine if r.external_id])
            except Exception:
                logger.exception(f"Could not poll the {backend} backend; its runs are polled again next pass.")
                continue
            for r in mine:
                if r.external_id in states:
                    observed[r.database_id] = states[r.external_id]
        return observed

    def internal_subscribe(self, queue: Queue[HpcRun], job_id: int) -> None:
        self.internal_listeners[job_id] = queue

    def internal_unsubscribe(self, job_id: int) -> None:
        self.internal_listeners.pop(job_id)

    async def close(self) -> None:
        await self.stop_polling()
