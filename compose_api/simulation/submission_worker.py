"""The submission worker (docs/plan-durable-submission.md, Q2): takes queued runs to SLURM, and survives restarts.

A request records its run as a ``requested`` submission (its files staged, compose_api/simulation/staging.py) and
wakes the worker. The worker leases due rows (``SKIP LOCKED``, so several workers never take the same one), and moves
each forward in short steps that each commit their own state:

    requested ──► preparing ──► submitting ──► submitted
        └────────────┴──────────────┴──► failed (reason, on a FAILED run)

- **preparing:** ``ensure_image``, as before (it finds a recorded image, or fetches or builds one, joining a build
  another process started). This can take minutes; the worker renews its lease meanwhile.
- **submitting:** sbatch, idempotently: a job already named for the run (an earlier attempt submitted it but died
  before recording it) is adopted instead of submitted again. The run and the move to ``submitted`` are recorded in
  one transaction.

A worker that disappears (an API restart) just stops renewing; its leases expire and the next worker resumes each row
from its state. A transient failure is retried with backoff; a permanent one, or one past the attempts or the overall
deadline, fails the run with its reason.
"""

import asyncio
import contextlib
import datetime
import functools
import logging
import os
import random
import string
import uuid

from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseService
from compose_api.observability.api_events import record_api_event
from compose_api.simulation import staging
from compose_api.simulation.hpc_utils import get_correlation_id
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import JobType, Simulation, Submission, SubmissionState
from compose_api.simulation.simulation_service import SimulationService

logger = logging.getLogger(__name__)

#: Backoff between attempts after a transient failure, in seconds; the last is repeated.
BACKOFF_SECONDS = (30, 60, 120, 240, 480)


class PermanentSubmissionError(Exception):
    """A failure no retry can fix: the run fails at once with this reason."""


class LostLeaseError(Exception):
    """The worker no longer holds the row (its lease expired and another worker took it): stop, write nothing."""


class SubmissionWorker:
    def __init__(
        self,
        database_service: DatabaseService,
        simulation_service: SimulationService,
        job_monitor: JobMonitor,
        *,
        owner: str | None = None,
    ) -> None:
        self.database_service = database_service
        self.simulation_service = simulation_service
        self.job_monitor = job_monitor
        self.owner = owner or f"{os.environ.get('HOSTNAME', 'api')}-{uuid.uuid4().hex[:8]}"
        self._wake = asyncio.Event()
        self._working: dict[int, asyncio.Task[None]] = {}
        self._loop: asyncio.Task[None] | None = None
        self._stopping = False

    # -- running -- #

    def kick(self) -> None:
        """A run was just queued: look now rather than at the next poll."""
        self._wake.set()

    def start(self) -> None:
        if self._loop is None:
            self._loop = asyncio.create_task(self._run_forever(), name="submission-worker")

    async def close(self) -> None:
        """Stop claiming, cancel the work in hand and give its rows back, so the next worker takes them at once."""
        self._stopping = True
        if self._loop is not None:
            self._loop.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop
        working = list(self._working.items())
        for _, task in working:
            task.cancel()
        for simulation_id, task in working:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            with contextlib.suppress(Exception):
                await self.database_service.get_hpc_db().release_submission(simulation_id, self.owner)

    async def _run_forever(self) -> None:
        poll = get_settings().submission_poll_seconds
        while not self._stopping:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Submission worker pass failed")
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=poll)

    async def run_once(self) -> list[int]:
        """Claim what fits in the free slots and start working on it; the simulations claimed."""
        settings = get_settings()
        free = settings.submission_worker_concurrency - len(self._working)
        if free <= 0:
            return []
        claimed = await self.database_service.get_hpc_db().claim_submissions(
            owner=self.owner,
            lease_seconds=settings.submission_lease_seconds,
            limit=free,
            exclude=frozenset(self._working),
        )
        for submission in claimed:
            if submission.state is not SubmissionState.REQUESTED:
                logger.info(f"Simulation {submission.simulation_id}: claimed, resuming from {submission.state}")
            task = asyncio.create_task(self._work(submission), name=f"submission-{submission.simulation_id}")
            self._working[submission.simulation_id] = task
            task.add_done_callback(functools.partial(self._done, submission.simulation_id))
        return [s.simulation_id for s in claimed]

    def _done(self, simulation_id: int, _task: "asyncio.Task[None]") -> None:
        self._working.pop(simulation_id, None)
        self.kick()  # a slot is free

    async def drain(self, timeout: float = 60.0) -> None:
        """Work until nothing is due or in hand (for tests and one-off use)."""
        async with asyncio.timeout(timeout):
            while True:
                claimed = await self.run_once()
                if self._working:
                    await asyncio.wait(list(self._working.values()), return_when=asyncio.FIRST_COMPLETED)
                elif not claimed:
                    return

    # -- one submission -- #

    async def _work(self, submission: Submission) -> None:
        step = asyncio.current_task()
        renewing = asyncio.create_task(self._keep_lease(submission.simulation_id, step))
        try:
            await self._advance(submission)
        except asyncio.CancelledError:
            if self._stopping:
                raise
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()  # the cancel was ours (a lost lease), handled here
            logger.warning(f"Simulation {submission.simulation_id}: lease lost; another worker resumes it")
        except LostLeaseError:
            logger.warning(f"Simulation {submission.simulation_id}: lease lost; another worker resumes it")
        except PermanentSubmissionError as e:
            await self._fail(submission, str(e))
        except Exception as e:
            await self._retry_or_fail(submission, e)
        finally:
            renewing.cancel()

    async def _keep_lease(self, simulation_id: int, step: "asyncio.Task[object] | None") -> None:
        """Renew the lease while the step works; cancel the step if the row was taken over."""
        hpc_db = self.database_service.get_hpc_db()
        lease = get_settings().submission_lease_seconds
        while True:
            await asyncio.sleep(max(1.0, lease / 3))
            try:
                held = await hpc_db.renew_submission_lease(simulation_id, self.owner, lease)
            except Exception:
                logger.exception(f"Simulation {simulation_id}: could not renew the submission lease")
                continue
            if not held and step is not None:
                step.cancel(msg="lost lease")
                return

    async def _advance(self, submission: Submission) -> None:
        hpc_db = self.database_service.get_hpc_db()
        simulator = await self.database_service.get_simulator_db().get_simulator(submission.simulator_id)
        if simulator is None:
            raise PermanentSubmissionError(f"its simulator {submission.simulator_id} no longer exists")
        simulation = Simulation(
            database_id=submission.simulation_id, sim_request=submission.request, simulator_version=simulator
        )
        _check_staged(submission)

        if submission.state in (SubmissionState.REQUESTED, SubmissionState.PREPARING):
            await self._move(submission, SubmissionState.PREPARING)
            from compose_api.simulation.handlers import ensure_image  # late: handlers imports this module

            try:
                await ensure_image(
                    simulator,
                    database_service=self.database_service,
                    simulation_service_slurm=self.simulation_service,
                    job_monitor=self.job_monitor,
                    random_string=_random7(),
                )
            except Exception as e:
                # as before the queue: a pull that fell back to a build which failed (or timed out) is not retried
                # here, since a build can take hours; resubmitting tries again
                raise PermanentSubmissionError(f"its image could not be made ready: {type(e).__name__}: {e}") from e
            await self._move(submission, SubmissionState.SUBMITTING)

        # submitting: adopt a job an earlier attempt submitted, or submit
        correlation_id = get_correlation_id(random_string=_random7(), job_type=JobType.SIMULATION)
        slurmjobid = await self.simulation_service.find_simulation_job(submission.experiment_id)
        adopted = slurmjobid is not None
        if slurmjobid is None:
            slurmjobid = await self.simulation_service.submit_simulation_job(
                simulation=simulation,
                experiment_id=submission.experiment_id,
                correlation_id=correlation_id,
                staged_on_store=submission.staged_on_store,
            )
        hpcrun = await hpc_db.complete_submission(submission.simulation_id, self.owner, slurmjobid, correlation_id)
        if hpcrun is None:
            raise LostLeaseError
        staging.remove_staging(submission.experiment_id, submission.staged_on_store)
        if adopted:
            logger.info(f"Simulation {submission.simulation_id}: adopted SLURM job {slurmjobid} submitted earlier")
        await record_api_event(
            self.database_service,
            hpcrun,
            "dispatch.submitted",
            {
                "slurm_job_id": slurmjobid,
                "simulation_id": submission.simulation_id,
                "simulator_id": simulator.database_id,
                "experiment_id": submission.experiment_id,
                "attempts": submission.attempts + 1,
                "adopted": adopted,
            },
        )

    async def _move(self, submission: Submission, state: SubmissionState) -> None:
        if not await self.database_service.get_hpc_db().set_submission_state(
            submission.simulation_id, self.owner, state
        ):
            raise LostLeaseError

    async def _retry_or_fail(self, submission: Submission, error: Exception) -> None:
        settings = get_settings()
        reason = f"{type(error).__name__}: {error}"[:2000]
        attempt = submission.attempts + 1
        age = (datetime.datetime.now() - submission.created_at).total_seconds()
        if attempt >= settings.submission_max_attempts:
            await self._fail(submission, f"Submission failed after {attempt} attempts: {reason}")
        elif age >= settings.submission_timeout_seconds:
            await self._fail(
                submission,
                f"Submission did not reach SLURM within {settings.submission_timeout_seconds} s; last error: {reason}",
            )
        else:
            delay = BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]
            logger.warning(f"Simulation {submission.simulation_id}: attempt {attempt} failed, retrying in {delay} s")
            await self.database_service.get_hpc_db().retry_submission(
                submission.simulation_id, self.owner, reason, delay
            )

    async def _fail(self, submission: Submission, reason: str) -> None:
        logger.error(f"Simulation {submission.simulation_id}: {reason}")
        await self.database_service.get_hpc_db().fail_submission(submission.simulation_id, reason)


def _check_staged(submission: Submission) -> None:
    """A run whose staged input is gone cannot be submitted, however often it is retried."""
    directory = staging.local_staging_dir(submission.experiment_id, submission.staged_on_store)
    name = submission.request.request_file_path.name
    if directory is not None and not (directory / name).is_file():
        raise PermanentSubmissionError(f"its staged input {name} is missing; resubmit the simulation")


def _random7() -> str:
    return "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
