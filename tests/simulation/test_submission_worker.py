"""The durable submission queue (docs/plan-durable-submission.md): a run is staged and recorded as `requested`, and the
submission worker takes it to SLURM exactly once, resuming what a lost worker left. These need only Postgres: the
cluster is a fake that records what would be submitted."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation import handlers
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import (
    JobStatus,
    JobType,
    RemoteContainerImage,
    Simulation,
    SimulationCancellation,
    SimulationRequest,
    SimulatorVersion,
    SubmissionState,
)
from compose_api.simulation.simulation_service import SimulationService
from compose_api.simulation.submission_worker import SubmissionWorker
from tests.fixtures.mocks import TestBackgroundTask


class FakeCluster:
    """sbatch and the job lookup by name, in memory; the image pull always succeeds."""

    def __init__(self) -> None:
        self.jobs: dict[str, int] = {}  # job name (experiment id) -> SLURM job id
        self.submitted: list[str] = []
        self.fail_submits = 0  # this many submissions raise first
        self.staged: list[bool] = []

    async def download_container(self, remote_container_image: RemoteContainerImage) -> None:
        return None

    async def find_simulation_job(self, experiment_id: str) -> int | None:
        return self.jobs.get(experiment_id)

    async def submit_simulation_job(
        self, simulation: Simulation, experiment_id: str, correlation_id: str, staged_on_store: bool = False
    ) -> int:
        if self.fail_submits > 0:
            self.fail_submits -= 1
            raise OSError("ssh: connection reset")
        assert simulation.sim_request.request_file_path.is_file(), "the worker submits from the staged file"
        self.staged.append(staged_on_store)
        self.submitted.append(experiment_id)
        job_id = 700000 + len(self.submitted)
        self.jobs[experiment_id] = job_id
        return job_id


@pytest.fixture
def staging_dir(tmp_path: Path) -> Iterator[Path]:
    # the store is not mounted in tests, so runs are staged in a local directory and uploaded from there
    with override_settings(submission_staging_dir=str(tmp_path / "staging")):
        yield tmp_path / "staging"


def _worker(database_service: DatabaseServiceSQL, cluster: FakeCluster, owner: str = "worker-a") -> SubmissionWorker:
    return SubmissionWorker(database_service, cast(SimulationService, cluster), cast(JobMonitor, None), owner=owner)


async def _queue(database_service: DatabaseServiceSQL, request: SimulationRequest, **placement: Any) -> int:
    experiment = await handlers.run_simulation(
        simulation_request=request,
        database_service=database_service,
        simulation_service_slurm=cast(SimulationService, None),
        job_monitor=cast(JobMonitor, None),
        background_tasks=TestBackgroundTask(),
        **placement,
    )
    return experiment.simulation_database_id


async def _set(engine: AsyncEngine, simulation_id: int, sql: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"UPDATE submission SET {sql} WHERE simulation_id = {simulation_id}"))  # noqa: S608


@pytest.mark.asyncio
async def test_a_queued_run_is_staged_then_submitted_once(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    staging_dir: Path,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    hpc_db = database_service.get_hpc_db()
    queued = await hpc_db.get_submission(simulation_id)
    assert queued is not None and queued.state is SubmissionState.REQUESTED
    # durable before the response: the input is a copy in the staging directory, not the caller's file
    staged = queued.request.request_file_path
    assert staged.is_file() and staged.parent == staging_dir / queued.experiment_id
    assert staged.read_bytes() == simulation_request.request_file_path.read_bytes()
    assert await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION) is None  # still "submitting" publicly

    cluster = FakeCluster()
    await _worker(database_service, cluster).drain()

    run = await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.slurmjobid == cluster.jobs[queued.experiment_id]
    assert cluster.submitted == [queued.experiment_id] and cluster.staged == [False]
    done = await hpc_db.get_submission(simulation_id)
    assert done is not None and done.state is SubmissionState.SUBMITTED
    assert not staged.parent.exists(), "the staging directory is removed once the run is on the cluster"
    await _worker(database_service, cluster).drain()
    assert len(cluster.submitted) == 1, "a submitted run is never claimed again"


@pytest.mark.asyncio
async def test_two_workers_never_submit_the_same_run(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    staging_dir: Path,
) -> None:  # fmt: skip
    ids = [await _queue(database_service, simulation_request) for _ in range(6)]
    cluster = FakeCluster()
    with override_settings(submission_worker_concurrency=2):
        await asyncio.gather(
            _worker(database_service, cluster, "worker-a").drain(),
            _worker(database_service, cluster, "worker-b").drain(),
        )
    assert len(cluster.submitted) == 6 and len(set(cluster.submitted)) == 6
    for simulation_id in ids:
        run = await database_service.get_hpc_db().get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
        assert run is not None and run.status == JobStatus.RUNNING


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [SubmissionState.REQUESTED, SubmissionState.PREPARING, SubmissionState.SUBMITTING])
async def test_a_lost_workers_run_is_resumed_from_its_state(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path, state: SubmissionState,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    # held by a worker that has gone: its lease ran out a minute ago
    await _set(
        async_postgres_engine, simulation_id,
        f"state = '{state.value}', lease_owner = 'gone', lease_expires_at = localtimestamp - interval '1 minute'",
    )  # fmt: skip
    cluster = FakeCluster()
    await _worker(database_service, cluster).drain()
    run = await database_service.get_hpc_db().get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.slurmjobid is not None
    assert len(cluster.submitted) == 1


@pytest.mark.asyncio
async def test_a_job_submitted_before_the_worker_died_is_adopted_not_resubmitted(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    submission = await database_service.get_hpc_db().get_submission(simulation_id)
    assert submission is not None
    await _set(
        async_postgres_engine, simulation_id,
        "state = 'submitting', lease_owner = 'gone', lease_expires_at = localtimestamp - interval '1 minute'",
    )  # fmt: skip
    cluster = FakeCluster()
    cluster.jobs[submission.experiment_id] = 812345  # its sbatch went through; recording it did not
    await _worker(database_service, cluster).drain()
    run = await database_service.get_hpc_db().get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.slurmjobid == 812345
    assert cluster.submitted == []


@pytest.mark.asyncio
async def test_a_live_lease_is_left_to_its_worker(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    await _set(
        async_postgres_engine, simulation_id,
        "lease_owner = 'busy', lease_expires_at = localtimestamp + interval '5 minutes'",
    )  # fmt: skip
    cluster = FakeCluster()
    await _worker(database_service, cluster).drain()
    assert cluster.submitted == []
    assert await database_service.get_hpc_db().get_hpcrun_by_ref(simulation_id, JobType.SIMULATION) is None


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_then_fails_with_its_reason(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    hpc_db = database_service.get_hpc_db()
    cluster = FakeCluster()
    cluster.fail_submits = 5
    with override_settings(submission_max_attempts=2):
        await _worker(database_service, cluster).drain()
        retrying = await hpc_db.get_submission(simulation_id)
        assert retrying is not None and retrying.attempts == 1 and "connection reset" in (retrying.last_error or "")
        assert await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION) is None  # not yet due again
        await _set(async_postgres_engine, simulation_id, "next_attempt_at = localtimestamp")
        await _worker(database_service, cluster).drain()
    run = await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.status == JobStatus.FAILED and run.slurmjobid is None
    assert run.error_message is not None and "after 2 attempts" in run.error_message
    failed = await hpc_db.get_submission(simulation_id)
    assert failed is not None and failed.state is SubmissionState.FAILED


@pytest.mark.asyncio
async def test_a_retry_that_succeeds_submits_once(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    cluster = FakeCluster()
    cluster.fail_submits = 1
    await _worker(database_service, cluster).drain()
    await _set(async_postgres_engine, simulation_id, "next_attempt_at = localtimestamp")
    await _worker(database_service, cluster).drain()
    run = await database_service.get_hpc_db().get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.status == JobStatus.RUNNING
    assert len(cluster.submitted) == 1


@pytest.mark.asyncio
async def test_a_missing_staged_input_fails_at_once(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    staging_dir: Path,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    submission = await database_service.get_hpc_db().get_submission(simulation_id)
    assert submission is not None
    submission.request.request_file_path.unlink()
    cluster = FakeCluster()
    await _worker(database_service, cluster).drain()
    run = await database_service.get_hpc_db().get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.status == JobStatus.FAILED
    assert run.error_message is not None and "staged input" in run.error_message
    assert cluster.submitted == []


@pytest.mark.asyncio
async def test_higher_priority_runs_are_claimed_first(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    staging_dir: Path,
) -> None:  # fmt: skip
    suite = [await _queue(database_service, simulation_request, queue="suite:x", priority=-10) for _ in range(3)]
    interactive = await _queue(database_service, simulation_request)
    claimed = await database_service.get_hpc_db().claim_submissions(owner="w", lease_seconds=60, limit=2)
    assert [c.simulation_id for c in claimed] == [interactive, suite[0]]
    assert claimed[1].queue == "suite:x" and claimed[1].priority == -10


@pytest.mark.asyncio
async def test_the_stale_check_leaves_queued_runs_to_the_worker(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    async with async_postgres_engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE simulation SET created_at = localtimestamp - interval '1 hour' WHERE id = {simulation_id}")  # noqa: S608
        )
    with override_settings(submission_stale_seconds=300):
        failed = await JobMonitor(database_service, slurm_service=cast(Any, None)).fail_stale_submissions()
    assert simulation_id not in failed


# -- cancelling a queued run ----------------------------------------------------------------------------------------


async def _cancel(database_service: DatabaseServiceSQL, simulation_id: int) -> SimulationCancellation:
    # no SLURM: a queued run is withdrawn in the database, so a cancel that reached the scheduler would raise here
    return await handlers.cancel_simulation(
        simulation_id, "auth0|alice", database_service, simulation_service_slurm=cast(SimulationService, None)
    )


@pytest.mark.asyncio
async def test_a_requested_run_is_withdrawn_and_never_submitted(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    staging_dir: Path,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    hpc_db = database_service.get_hpc_db()
    queued = await hpc_db.get_submission(simulation_id)
    assert queued is not None

    cancelled = await _cancel(database_service, simulation_id)

    assert cancelled.withdrawn and cancelled.slurm_job_id is None
    run = await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.status == JobStatus.CANCELLED and run.slurmjobid is None
    assert run.error_message == "Cancelled by a signed-in user", "who cancelled is never in the readable record"
    after = await hpc_db.get_submission(simulation_id)
    assert after is not None and after.state is SubmissionState.FAILED
    assert not (staging_dir / queued.experiment_id).exists(), "a withdrawn run's staged files are removed"
    cluster = FakeCluster()
    await _worker(database_service, cluster).drain()
    assert cluster.submitted == []
    with pytest.raises(handlers.CancelRefusedError, match="already finished"):
        await _cancel(database_service, simulation_id)


@pytest.mark.asyncio
async def test_withdrawing_a_preparing_run_takes_the_lease_from_its_worker(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    # a live worker is fetching its image
    await _set(
        async_postgres_engine, simulation_id,
        "state = 'preparing', lease_owner = 'busy', lease_expires_at = localtimestamp + interval '5 minutes'",
    )  # fmt: skip
    assert (await _cancel(database_service, simulation_id)).withdrawn

    hpc_db = database_service.get_hpc_db()
    # the worker's next steps both check its lease, so it stops before sbatch
    assert not await hpc_db.set_submission_state(simulation_id, "busy", SubmissionState.SUBMITTING)
    assert await hpc_db.complete_submission(simulation_id, "busy", 812345, "corr-too-late") is None
    run = await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.status == JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_a_run_being_sbatched_is_not_withdrawn(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    simulation_id = await _queue(database_service, simulation_request)
    await _set(
        async_postgres_engine, simulation_id,
        "state = 'submitting', lease_owner = 'busy', lease_expires_at = localtimestamp + interval '5 minutes'",
    )  # fmt: skip
    with pytest.raises(handlers.CancelRefusedError, match="being submitted"):
        await _cancel(database_service, simulation_id)
    hpc_db = database_service.get_hpc_db()
    assert await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION) is None
    assert await hpc_db.complete_submission(simulation_id, "busy", 812345, "corr-in-time") is not None


@pytest.mark.asyncio
async def test_a_withdrawal_racing_the_worker_has_exactly_one_outcome(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    """The worker's last two steps (move to submitting, record the job) against a withdrawal, on real Postgres: never
    both a SLURM job and a cancelled run."""
    hpc_db = database_service.get_hpc_db()
    for i in range(12):
        simulation_id = await _queue(database_service, simulation_request)
        await _set(
            async_postgres_engine, simulation_id,
            "state = 'preparing', lease_owner = 'w', lease_expires_at = localtimestamp + interval '5 minutes'",
        )  # fmt: skip

        async def worker(simulation_id: int = simulation_id, i: int = i) -> bool:
            if not await hpc_db.set_submission_state(simulation_id, "w", SubmissionState.SUBMITTING):
                return False
            return await hpc_db.complete_submission(simulation_id, "w", 900000 + i, f"corr-race-{i}") is not None

        withdrawn, submitted = await asyncio.gather(
            hpc_db.withdraw_submission(simulation_id, "Cancelled by auth0|alice"), worker()
        )
        assert (withdrawn is not None) != submitted, "exactly one of withdraw and submit wins"
        run = await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
        assert run is not None
        assert run.status == (JobStatus.CANCELLED if withdrawn is not None else JobStatus.RUNNING)


@pytest.mark.asyncio
async def test_a_withdrawal_waiting_on_a_submission_does_not_deadlock_its_run_insert(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    """The interleaving made deterministic: complete_submission holds the submission row, the withdrawal locks the
    simulation and waits for that row, then the run insert's foreign-key check asks for KEY SHARE on the simulation.
    Under FOR UPDATE on the simulation that is a deadlock, which Postgres breaks by aborting one; under FOR NO KEY
    UPDATE the insert goes ahead and the withdrawal finds the run."""
    simulation_id = await _queue(database_service, simulation_request)
    await _set(async_postgres_engine, simulation_id, "state = 'preparing'")
    async with async_postgres_engine.connect() as held:
        await held.begin()
        await held.execute(text(f"SELECT 1 FROM submission WHERE simulation_id = {simulation_id} FOR UPDATE"))  # noqa: S608
        withdrawal = asyncio.create_task(
            database_service.get_hpc_db().withdraw_submission(simulation_id, "Cancelled by auth0|alice")
        )
        async with async_postgres_engine.connect() as probe:  # wait until the withdrawal is blocked on our row
            for _ in range(100):
                waiting = await probe.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                    )
                )
                if waiting.scalar_one():
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("the withdrawal never waited on the submission row")
        # what the run insert's foreign-key check takes on the simulation
        await held.execute(text(f"SELECT 1 FROM simulation WHERE id = {simulation_id} FOR KEY SHARE"))  # noqa: S608
        await held.execute(text(f"UPDATE submission SET state = 'submitted' WHERE simulation_id = {simulation_id}"))  # noqa: S608
        await held.commit()
    assert await asyncio.wait_for(withdrawal, timeout=10) is None, "the submission moved on, so nothing is withdrawn"


@pytest.mark.asyncio
async def test_failing_a_submission_waits_for_a_run_being_recorded(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    """A worker that lost its lease fails the run while another worker is recording its SLURM job: the failure waits
    on the submission row, sees the committed run, and records nothing, so a running job never gains a FAILED twin."""
    simulation_id = await _queue(database_service, simulation_request)
    await _set(async_postgres_engine, simulation_id, "state = 'submitting', lease_owner = 'b'")
    hpc_db = database_service.get_hpc_db()
    async with async_postgres_engine.connect() as held:  # worker b inside complete_submission, not yet committed
        await held.begin()
        await held.execute(text(f"SELECT 1 FROM submission WHERE simulation_id = {simulation_id} FOR UPDATE"))  # noqa: S608
        failing = asyncio.create_task(hpc_db.fail_submission(simulation_id, "worker a gave up"))
        await asyncio.sleep(0.5)
        assert not failing.done(), "the failure waits for the submission row"
        await held.execute(
            text(
                "INSERT INTO hpcrun (job_type, correlation_id, slurmjobid, backend, status, simulation_id)"  # noqa: S608
                f" VALUES ('SIMULATION', 'corr-b-{simulation_id}', 905001, 'slurm', 'RUNNING', {simulation_id})"
            )
        )
        await held.execute(text(f"UPDATE submission SET state = 'submitted' WHERE simulation_id = {simulation_id}"))  # noqa: S608
        await held.commit()
    assert await asyncio.wait_for(failing, timeout=10) is None
    async with async_postgres_engine.connect() as conn:
        statuses = (
            (
                await conn.execute(text(f"SELECT status FROM hpcrun WHERE simulation_id = {simulation_id}"))  # noqa: S608
            )
            .scalars()
            .all()
        )
    assert list(statuses) == ["RUNNING"], "one run, the one being recorded"
