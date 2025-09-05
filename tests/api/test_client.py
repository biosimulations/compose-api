import asyncio

import pytest

from compose_api.api.client import Client
from compose_api.api.client.api.simulations import get_simulation_status, run_simulation
from compose_api.api.client.models import HpcRun, JobStatus, SimulationExperiment
from compose_api.api.client.models.body_run_simulation import BodyRunSimulation
from compose_api.api.client.types import File
from compose_api.common.gateway.models import ServerMode
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.job_scheduler import JobScheduler
from compose_api.simulation.models import SimulationRequest
from compose_api.simulation.simulation_service import SimulationServiceHpc
from compose_api.version import __version__

server_urls = [ServerMode.DEV, ServerMode.PROD]
current_version = __version__


@pytest.mark.asyncio
async def test_sim_run(
    in_memory_api_client: Client,
    simulation_request: SimulationRequest,
    database_service: DatabaseServiceSQL,
    simulation_service_slurm: SimulationServiceHpc,
    job_scheduler: JobScheduler,
) -> None:
    assert simulation_request.omex_archive is not None
    with open(simulation_request.omex_archive, "rb") as f:
        sim_experiment = await run_simulation.asyncio(
            client=in_memory_api_client, body=BodyRunSimulation(uploaded_file=File(file_name=f.name, payload=f))
        )
        assert isinstance(sim_experiment, SimulationExperiment)

        current_status = await get_simulation_status.asyncio(
            client=in_memory_api_client, simulation_id=sim_experiment.simulation.database_id
        )

        if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
            raise TypeError()

        num_loops = 0
        while current_status.status != JobStatus.COMPLETED and num_loops < 10:
            await asyncio.sleep(2)
            current_status = await get_simulation_status.asyncio(
                client=in_memory_api_client, simulation_id=sim_experiment.simulation.database_id
            )
            num_loops += 1

            if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
                raise TypeError()

        current_status = await get_simulation_status.asyncio(
            client=in_memory_api_client, simulation_id=sim_experiment.simulation.database_id
        )

        if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
            raise TypeError()

        assert current_status.status == JobStatus.COMPLETED

    # response = await httpx_client.get("/version")
    # assert response.status_code == 200
    # data = response.json()
    # assert data == current_version
