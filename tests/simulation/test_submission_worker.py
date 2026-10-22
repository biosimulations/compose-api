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
