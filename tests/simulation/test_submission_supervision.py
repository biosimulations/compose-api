"""Submissions that never reach SLURM end as FAILED runs with a reason, not "submitting" forever (#238).

The submission worker (tests/simulation/test_submission_worker.py) now owns every queued run and resumes it after a
restart. The job monitor's `fail_stale_submissions` stays as a safety net for a simulation with no queued submission:
one recorded before the queue, or by an older API process during a rolling deploy. These need only Postgres.
"""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
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
async def test_a_late_failure_cannot_overwrite_a_run_that_reached_slurm(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion
) -> None:
    simulation_id = await _simulation(database_service, simulation_request, simulator, "submitted")
    hpc_db = database_service.get_hpc_db()
    await hpc_db.insert_hpcrun(slurmjobid=94001, job_type=JobType.SIMULATION, ref_id=simulation_id, correlation_id="c1")
    assert await hpc_db.fail_submission(simulation_id, "late") is None
    run = await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    assert run is not None and run.slurmjobid == 94001
