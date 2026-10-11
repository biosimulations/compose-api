"""The set of jobs the monitor polls.

`JobMonitor` re-reads this set on every tick, so a run missing from it is never updated
again. These tests need only Postgres, so they run everywhere, unlike the SLURM tests
that first exposed the behaviour.
"""

from typing import Any

import pytest

from compose_api.common.hpc.models import SlurmJob
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import JobStatus, JobType, SimulationRequest, SimulatorVersion

TERMINAL = [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMEOUT, JobStatus.OUT_OF_MEMORY]
UNFINISHED = [JobStatus.PENDING, JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.WAITING, JobStatus.SUSPENDED]


async def _insert_run(
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
    slurmjobid: int,
    status: JobStatus,
) -> int:
    simulation = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request, experiment_id=f"exp-{slurmjobid}", simulator_version=simulator
    )
    hpcrun = await database_service.get_hpc_db().insert_hpcrun(
        slurmjobid=slurmjobid,
        job_type=JobType.SIMULATION,
        ref_id=simulation.database_id,
        correlation_id=f"corr-{slurmjobid}",
    )
    await database_service.get_hpc_db().update_hpcrun_status(
        hpcrun_id=hpcrun.database_id,
        new_slurm_job=SlurmJob(
            job_id=slurmjobid, name="probe", account="acct", user_name="user", job_state=status.value
        ),
    )
    return hpcrun.database_id


@pytest.mark.asyncio
async def test_pending_job_is_still_polled(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion
) -> None:
    """A job the scheduler reports as PENDING must stay in the polling set.

    It was previously dropped the moment the monitor wrote PENDING, which stranded the
    run in that status forever: it never reached COMPLETED and the API never saw results.
    """
    hpcrun_id = await _insert_run(database_service, simulation_request, simulator, 90001, JobStatus.PENDING)
    try:
        polled = await database_service.get_hpc_db().list_unfinished_hpcruns()
        assert hpcrun_id in [run.database_id for run in polled]
    finally:
        await database_service.get_hpc_db().delete_hpcrun(hpcrun_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", UNFINISHED, ids=[s.value for s in UNFINISHED])
async def test_unfinished_statuses_are_polled(
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
    status: JobStatus,
) -> None:
    hpcrun_id = await _insert_run(
        database_service, simulation_request, simulator, 91000 + UNFINISHED.index(status), status
    )
    try:
        polled = await database_service.get_hpc_db().list_unfinished_hpcruns()
        assert hpcrun_id in [run.database_id for run in polled], f"{status.value} should still be polled"
    finally:
        await database_service.get_hpc_db().delete_hpcrun(hpcrun_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", TERMINAL, ids=[s.value for s in TERMINAL])
async def test_terminal_statuses_are_not_polled(
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
    status: JobStatus,
) -> None:
    hpcrun_id = await _insert_run(
        database_service, simulation_request, simulator, 92000 + TERMINAL.index(status), status
    )
    try:
        polled = await database_service.get_hpc_db().list_unfinished_hpcruns()
        assert hpcrun_id not in [run.database_id for run in polled], f"{status.value} is terminal"
    finally:
        await database_service.get_hpc_db().delete_hpcrun(hpcrun_id)


class _ReportsRunning:
    """A SLURM service that reports every job it is asked about as RUNNING."""

    async def get_job_status_squeue(self, job_ids: list[int]) -> list[SlurmJob]:
        return [
            SlurmJob(job_id=job_id, name="probe", account="acct", user_name="user", job_state="RUNNING")
            for job_id in job_ids
        ]

    async def get_job_status_sacct(self, job_ids: list[int]) -> list[SlurmJob]:
        return []


@pytest.mark.asyncio
async def test_one_failed_update_does_not_stop_the_others(
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database error on one run (production's jobstatusdb once lacked PENDING) used to abort the whole pass."""
    broken = await _insert_run(database_service, simulation_request, simulator, 93001, JobStatus.WAITING)
    healthy = await _insert_run(database_service, simulation_request, simulator, 93002, JobStatus.WAITING)
    hpc_db = database_service.get_hpc_db()
    update = hpc_db.update_hpcrun_status

    async def fail_for_broken(hpcrun_id: int, new_slurm_job: SlurmJob) -> None:
        if hpcrun_id == broken:
            raise RuntimeError("invalid input value for enum jobstatusdb")
        await update(hpcrun_id=hpcrun_id, new_slurm_job=new_slurm_job)

    monkeypatch.setattr(hpc_db, "update_hpcrun_status", fail_for_broken)
    slurm: Any = _ReportsRunning()
    try:
        await JobMonitor(database_service, slurm_service=slurm).update_running_jobs()
        statuses = {run.database_id: run.status for run in await hpc_db.list_unfinished_hpcruns()}
        assert statuses[healthy] == JobStatus.RUNNING
        assert statuses[broken] == JobStatus.WAITING
    finally:
        monkeypatch.undo()
        await hpc_db.delete_hpcrun(broken)
        await hpc_db.delete_hpcrun(healthy)
