"""What the API says when a client asks for something that does not exist.

These need only Postgres, so they run everywhere. The point is not that an error is
raised but that the *right* one is: a resource a client named incorrectly is a 404, and
only a genuine server fault is a 500. Reporting "Internal Server Error" for a mistyped id
tells the caller to retry and tells us to go looking for a bug that is not there.

`pbest` is the caller that matters. It polls these endpoints by id, so "never" and "not
yet" are states it has to tell apart.

They drive `http_api_client` rather than the generated client, because the status code is
the assertion. The generated client is configured to raise on any status the OpenAPI spec
does not declare, and the spec declares none of these -- see the note at the bottom.
"""

import httpx
import pytest

from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.dependencies import get_data_service, set_data_service
from compose_api.simulation.data_service import DataServiceHpc
from compose_api.simulation.models import JobType, SimulationRequest, SimulatorVersion

# Far above anything a test inserts, so it cannot collide with a real row.
ABSENT_ID = 987_654_321


@pytest.mark.asyncio
async def test_simulation_status_for_absent_id_is_404(
    http_api_client: httpx.AsyncClient, database_service: DatabaseServiceSQL
) -> None:
    response = await http_api_client.get("/results/simulation/status", params={"simulation_id": ABSENT_ID})
    assert response.status_code == 404
    assert str(ABSENT_ID) in response.text


@pytest.mark.asyncio
async def test_simulator_build_status_for_absent_id_is_404(
    http_api_client: httpx.AsyncClient, database_service: DatabaseServiceSQL
) -> None:
    response = await http_api_client.get("/results/simulator/build/status", params={"simulator_id": ABSENT_ID})
    assert response.status_code == 404
    assert str(ABSENT_ID) in response.text


@pytest.mark.asyncio
async def test_results_file_for_absent_simulation_is_404(
    http_api_client: httpx.AsyncClient, database_service: DatabaseServiceSQL
) -> None:
    """Previously a 500: the database layer's LookupError was swallowed with everything else."""
    saved = get_data_service()
    set_data_service(DataServiceHpc())
    try:
        response = await http_api_client.get("/results/simulation/results/file", params={"simulation_id": ABSENT_ID})
        assert response.status_code == 404
        assert str(ABSENT_ID) in response.text
    finally:
        set_data_service(saved)


@pytest.mark.asyncio
async def test_results_file_for_simulation_without_results_is_404(
    http_api_client: httpx.AsyncClient,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    """The simulation exists but has produced nothing yet, which is a client-visible state.

    `DataServiceHpc` builds the results path without checking it, so without the guard in
    the router this reached `FileResponse` and failed while streaming, after the status
    line had already been sent. Uses the production data service deliberately: the test
    double fetches over SSH, which is a different code path and not the one shipped.
    """
    simulation = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request, experiment_id="experiment-with-no-results", simulator_version=simulator
    )
    saved = get_data_service()
    set_data_service(DataServiceHpc())
    try:
        response = await http_api_client.get(
            "/results/simulation/results/file", params={"simulation_id": simulation.database_id}
        )
        assert response.status_code == 404
        assert "not available" in response.text
    finally:
        set_data_service(saved)
        await database_service.get_simulator_db().delete_simulation(simulation.database_id)


@pytest.mark.asyncio
async def test_batch_status_returns_only_the_ids_that_exist(
    http_api_client: httpx.AsyncClient,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    """The batch endpoint answers partially rather than failing, and this pins that.

    A caller polling a batch cannot otherwise tell a missing id from one with no run yet,
    so the contract is worth asserting rather than assuming.
    """
    simulation = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request, experiment_id="experiment-batch-partial", simulator_version=simulator
    )
    hpcrun = await database_service.get_hpc_db().insert_hpcrun(
        slurmjobid=4242,
        job_type=JobType.SIMULATION,
        ref_id=simulation.database_id,
        correlation_id="corr-batch-partial",
    )
    try:
        # The endpoint takes its ids as a JSON body on a GET, which is how the generated
        # client calls it and therefore how pbest does.
        response = await http_api_client.request(
            "GET", "/results/simulations/status/batch", json=[simulation.database_id, ABSENT_ID]
        )
        assert response.status_code == 200
        assert [run["sim_id"] for run in response.json()] == [simulation.database_id]
    finally:
        await database_service.get_hpc_db().delete_hpcrun(hpcrun.database_id)
        await database_service.get_simulator_db().delete_simulation(simulation.database_id)


@pytest.mark.asyncio
async def test_batch_status_for_all_absent_ids_is_an_empty_list(
    http_api_client: httpx.AsyncClient, database_service: DatabaseServiceSQL
) -> None:
    response = await http_api_client.request(
        "GET", "/results/simulations/status/batch", json=[ABSENT_ID, ABSENT_ID + 1]
    )
    assert response.status_code == 200
    assert response.json() == []
