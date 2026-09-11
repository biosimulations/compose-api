import asyncio
import random
import string
import tempfile
import time
import uuid
from pathlib import Path

import pytest
from nats.aio.client import Client as NATSClient

from compose_api.common.hpc.models import SlurmJob
from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.hpc_utils import _namespace_path, get_correlation_id, get_experiment_id
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import (
    HpcRun,
    JobStatus,
    JobType,
    SimulationFileType,
    SimulationRequest,
    SimulatorVersion,
    WorkerEvent,
)


async def insert_job(database_service: DatabaseServiceSQL, slurmjobid: int, simulator: SimulatorVersion) -> HpcRun:
    simulation_request = SimulationRequest(
        request_file_path=Path(""), simulation_file_type=SimulationFileType.OMEX, is_batch=False
    )
    random_string = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
    experiement_id = get_experiment_id(simulator, random_string)

    simulation = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request, experiment_id=experiement_id, simulator_version=simulator
    )
    slurm_job = SlurmJob(
        job_id=slurmjobid,
        name="name",
        account="acct",
        user_name="user",
        job_state="RUNNING",
    )

    correlation_id = get_correlation_id(random_string=random_string, job_type=JobType.SIMULATION)
    hpcrun = await database_service.get_hpc_db().insert_hpcrun(
        slurmjobid=slurm_job.job_id,
        job_type=JobType.SIMULATION,
        ref_id=simulation.database_id,
        correlation_id=correlation_id,
    )

    return hpcrun


async def wait_for_status(
    database_service: DatabaseServiceSQL, slurmjobid: int, expected: JobStatus, timeout_seconds: float
) -> HpcRun:
    """Poll until the monitor has written `expected`, or fail saying what it last saw.

    Sleeping a fixed interval and asserting once makes the result depend on how quickly
    the scheduler happens to dispatch, which differs between the throwaway container and
    a busy cluster. Polling lets the one test body be deterministic on both.
    """
    deadline = time.monotonic() + timeout_seconds
    last: HpcRun | None = None
    while time.monotonic() < deadline:
        last = await database_service.get_hpc_db().get_hpcrun_by_slurmjobid(slurmjobid=slurmjobid)
        if last is not None and last.status == expected:
            return last
        await asyncio.sleep(0.5)
    raise AssertionError(
        f"slurm job {slurmjobid} never reached {expected.value} within {timeout_seconds}s; "
        f"last status was {last.status if last else 'no hpcrun row'}"
    )


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_messaging(
    nats_subscriber_client: NATSClient,
    nats_producer_client: NATSClient,
    database_service: DatabaseServiceSQL,
    slurm_service: SlurmService,
    simulator: SimulatorVersion,
) -> None:
    monitor = JobMonitor(
        nats_client=nats_subscriber_client, database_service=database_service, slurm_service=slurm_service
    )
    await monitor.subscribe_nats()

    # Simulate a job submission and worker event handling
    hpc_run = await insert_job(database_service=database_service, slurmjobid=1, simulator=simulator)

    # get the initial state of a job
    sequence_number = 1
    worker_event = WorkerEvent(
        sequence_number=sequence_number,
        correlation_id=hpc_run.correlation_id,
        time=0.1,
        mass={"water": 1.0, "glucose": 0.5},
    )

    # send worker messages to the broker
    await nats_producer_client.publish(
        subject=get_settings().nats_worker_event_subject,
        payload=worker_event.model_dump_json(exclude_unset=True, exclude_none=True).encode("utf-8"),
    )
    # get the updated state of the job
    await asyncio.sleep(0.1)
    _updated_worker_events = await database_service.get_hpc_db().list_worker_events(
        hpcrun_id=hpc_run.database_id, prev_sequence_number=sequence_number - 1
    )
    assert len(_updated_worker_events) == 1


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_job_monitor(
    nats_subscriber_client: NATSClient,
    database_service: DatabaseServiceSQL,
    slurm_service: SlurmService,
    slurm_template_hello_10s: str,
    simulator: SimulatorVersion,
) -> None:
    monitor = JobMonitor(
        nats_client=nats_subscriber_client, database_service=database_service, slurm_service=slurm_service
    )
    await monitor.subscribe_nats()
    await monitor.start_polling(interval_seconds=1)

    # Submit a toy slurm job which takes 10 seconds to run
    _all_jobs_before_submit: list[SlurmJob] = await slurm_service.get_job_status_squeue()
    remote_path = _namespace_path() / "slurm_sbatch"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_dir = Path(tmpdir)
        # write slurm_template_hello_1s to a temp file
        local_sbatch_file = tmp_dir / f"job_{uuid.uuid4().hex}.sbatch"
        with open(local_sbatch_file, "w") as f:
            f.write(slurm_template_hello_10s)

        remote_sbatch_file = remote_path / local_sbatch_file.name
        job_id: int = await slurm_service._submit_canary_job(
            local_sbatch_file=local_sbatch_file,
            remote_sbatch_file=remote_sbatch_file,
        )

    # Simulate job submission
    hpc_run = await insert_job(database_service=database_service, slurmjobid=job_id, simulator=simulator)
    assert hpc_run.status == JobStatus.RUNNING

    # The monitor should see the job start, then finish. The sbatch script sleeps 10s and
    # the monitor polls every second, so RUNNING cannot be stepped over.
    running_hpcrun = await wait_for_status(database_service, job_id, JobStatus.RUNNING, timeout_seconds=120)
    assert running_hpcrun.status == JobStatus.RUNNING

    completed_hpcrun = await wait_for_status(database_service, job_id, JobStatus.COMPLETED, timeout_seconds=120)
    assert completed_hpcrun.status == JobStatus.COMPLETED

    # Stop polling
    await monitor.stop_polling()
