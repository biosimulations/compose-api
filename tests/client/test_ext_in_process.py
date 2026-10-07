"""The application layer against the real FastAPI app, in process (``AsyncComposeSession.in_process``).

These need only Postgres. They pin how ``ext`` reads the service's actual answers: a 404 on a status is "submitting"
(the service has the simulation but no SLURM job yet, or not at all), a 404 on results is ``NotFound``, and the batch
status answers only the ids that have a job.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from compose_api_client.ext import AsyncComposeSession, NotFound

from compose_api.api.main import app
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.dependencies import get_data_service, set_data_service
from compose_api.simulation.data_service import DataServiceHpc
from compose_api.simulation.models import JobType, SimulationRequest, SimulatorVersion
from compose_api.version import __version__

ABSENT_ID = 987_654_321


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncComposeSession]:
    async with AsyncComposeSession.in_process(app) as s:
        yield s


@pytest.mark.asyncio
async def test_health_and_version(session: AsyncComposeSession) -> None:
    assert (await session.health())["version"] == __version__
    assert await session.version() == __version__


@pytest.mark.asyncio
async def test_status_without_a_job_is_submitting(
    session: AsyncComposeSession, database_service: DatabaseServiceSQL
) -> None:
    state = await session.status(ABSENT_ID)
    assert state.status == "submitting" and not state.terminal
    assert (await session.build_status(ABSENT_ID)).status == "submitting"


@pytest.mark.asyncio
async def test_results_before_any_exist_is_not_found(
    session: AsyncComposeSession, database_service: DatabaseServiceSQL
) -> None:
    saved = get_data_service()
    set_data_service(DataServiceHpc())
    try:
        with pytest.raises(NotFound) as err:
            await session.results(ABSENT_ID)
        assert str(ABSENT_ID) in str(err.value.detail)
    finally:
        set_data_service(saved)


@pytest.mark.asyncio
async def test_status_and_batch_status_of_a_real_job(
    session: AsyncComposeSession,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    simulation = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request, experiment_id="experiment-ext-status", simulator_version=simulator
    )
    hpcrun = await database_service.get_hpc_db().insert_hpcrun(
        slurmjobid=4243, job_type=JobType.SIMULATION, ref_id=simulation.database_id, correlation_id="corr-ext"
    )
    try:
        state = await session.status(simulation.database_id)
        assert state.slurm_job == 4243 and state.record is not None
        runs = await session.statuses([simulation.database_id, ABSENT_ID])
        assert [r.sim_id for r in runs] == [simulation.database_id]
    finally:
        await database_service.get_hpc_db().delete_hpcrun(hpcrun.database_id)
        await database_service.get_simulator_db().delete_simulation(simulation.database_id)
