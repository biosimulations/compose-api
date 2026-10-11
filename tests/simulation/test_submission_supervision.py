"""Submissions that never reach SLURM end as FAILED runs with a reason, not "submitting" forever (#238).

Two ways a submission was stranded: its background task raised (a failed container fetch), or the API process
running it stopped (a deploy). `supervise_dispatch` covers the first and heartbeats while it works; the job monitor's
`fail_stale_submissions` covers the second. These need only Postgres.
"""

import asyncio
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.handlers import supervise_dispatch
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import JobStatus, JobType, SimulationRequest, SimulatorVersion


async def _simulation(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion, name: str
) -> int:
    simulation = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request, experiment_id=f"exp-supervision-{name}", simulator_version=simulator
    )
    return simulation.database_id


async def _age(engine: AsyncEngine, simulation_id: int, *, created: int, heartbeat: int | None) -> None:
    """Backdate the simulation's creation and heartbeat by these many seconds (None: no heartbeat)."""
    beat = "NULL" if heartbeat is None else f"localtimestamp - make_interval(secs => {heartbeat})"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"UPDATE simulation SET created_at = localtimestamp - make_interval(secs => {created}),"  # noqa: S608
                f" dispatch_heartbeat_at = {beat} WHERE id = {simulation_id}"
            )
        )


def _monitor(database_service: DatabaseServiceSQL) -> JobMonitor:
    slurm: Any = None  # fail_stale_submissions never calls SLURM
    return JobMonitor(database_service, slurm_service=slurm)


@pytest.mark.asyncio
async def test_a_submission_whose_task_is_gone_is_failed_with_a_reason(
    database_service: DatabaseServiceSQL,
    async_postgres_engine: AsyncEngine,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    never_beat = await _simulation(database_service, simulation_request, simulator, "never-beat")
    stopped = await _simulation(database_service, simulation_request, simulator, "stopped")
    await _age(async_postgres_engine, never_beat, created=3600, heartbeat=None)
    await _age(async_postgres_engine, stopped, created=3600, heartbeat=600)
    with override_settings(submission_stale_seconds=300):
        failed = await _monitor(database_service).fail_stale_submissions()
    assert {never_beat, stopped} <= set(failed)
    for simulation_id in (never_beat, stopped):
        run = await database_service.get_hpc_db().get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
        assert run is not None
        assert run.status == JobStatus.FAILED
        assert run.slurmjobid is None
        assert run.error_message is not None and "resubmit" in run.error_message


@pytest.mark.asyncio
async def test_a_submission_still_in_progress_is_left_alone(
    database_service: DatabaseServiceSQL,
    async_postgres_engine: AsyncEngine,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    just_created = await _simulation(database_service, simulation_request, simulator, "just-created")
    beating = await _simulation(database_service, simulation_request, simulator, "beating")
    await _age(async_postgres_engine, beating, created=3600, heartbeat=10)
    with override_settings(submission_stale_seconds=300):
        failed = await _monitor(database_service).fail_stale_submissions()
    assert just_created not in failed
    assert beating not in failed
    for simulation_id in (just_created, beating):
        assert await database_service.get_hpc_db().get_hpcrun_by_ref(simulation_id, JobType.SIMULATION) is None


@pytest.mark.asyncio
async def test_a_submission_that_raises_fails_the_simulation(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion
) -> None:
    simulation_id = await _simulation(database_service, simulation_request, simulator, "raises")

    async def dispatch() -> None:
        raise OSError("failed to send file singularity.def")

    await supervise_dispatch(database_service.get_hpc_db(), simulation_id, dispatch())
    run = await database_service.get_hpc_db().get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.status == JobStatus.FAILED
    assert run.error_message == "Submission failed before reaching SLURM: OSError: failed to send file singularity.def"


@pytest.mark.asyncio
async def test_a_submission_that_outlives_the_timeout_fails_the_simulation(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion
) -> None:
    simulation_id = await _simulation(database_service, simulation_request, simulator, "timeout")
    with override_settings(submission_timeout_seconds=1):
        await supervise_dispatch(database_service.get_hpc_db(), simulation_id, asyncio.sleep(60))
    run = await database_service.get_hpc_db().get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.status == JobStatus.FAILED
    assert run.error_message is not None and "within 1 s" in run.error_message


@pytest.mark.asyncio
async def test_a_submission_that_reaches_slurm_heartbeats_and_is_not_failed(
    database_service: DatabaseServiceSQL,
    async_postgres_engine: AsyncEngine,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    simulation_id = await _simulation(database_service, simulation_request, simulator, "submitted")
    hpc_db = database_service.get_hpc_db()

    async def dispatch() -> None:
        await asyncio.sleep(0.1)  # the heartbeat task runs first
        await hpc_db.insert_hpcrun(
            slurmjobid=94001, job_type=JobType.SIMULATION, ref_id=simulation_id, correlation_id="corr-94001"
        )

    await supervise_dispatch(hpc_db, simulation_id, dispatch())
    run = await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.slurmjobid == 94001
    # A late failure (or the monitor) cannot overwrite a run that reached SLURM.
    assert await hpc_db.fail_submission(simulation_id, "late") is None
    async with async_postgres_engine.connect() as conn:
        beat = await conn.execute(text(f"SELECT dispatch_heartbeat_at FROM simulation WHERE id = {simulation_id}"))  # noqa: S608
        assert beat.scalar_one() is not None
