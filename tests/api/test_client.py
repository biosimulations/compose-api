import asyncio
import tempfile
from pathlib import Path

import pytest

from compose_api.api.client import Client
from compose_api.api.client.api.simulations import get_simulation_results_file, get_simulation_status, run_simulation
from compose_api.api.client.models import HpcRun, JobStatus, SimulationExperiment
from compose_api.api.client.models.body_run_simulation import BodyRunSimulation
from compose_api.api.client.types import File
from compose_api.common.gateway.models import ServerMode
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.data_service import DataService
from compose_api.simulation.job_scheduler import JobMonitor
from compose_api.simulation.models import SimulationRequest, Simulator
from compose_api.simulation.simulation_service import SimulationServiceHpc
from compose_api.version import __version__
from tests.fixtures import simulation_fixtures

server_urls = [ServerMode.DEV, ServerMode.PROD]
current_version = __version__


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_sim_run(
    in_memory_api_client: Client,
        simulation_request_pypi: SimulationRequest,
    database_service: DatabaseServiceSQL,
    simulation_service_slurm: SimulationServiceHpc,
    job_scheduler: JobMonitor,
    data_service: DataService,
    simulator: Simulator,
) -> None:
    assert simulation_request_pypi.omex_archive is not None
    with open(simulation_request_pypi.omex_archive, "rb") as f:
        sim_experiment = await run_simulation.asyncio(
            client=in_memory_api_client, body=BodyRunSimulation(uploaded_file=File(file_name=f.name, payload=f))
        )
        assert isinstance(sim_experiment, SimulationExperiment)

        current_status = await get_simulation_status.asyncio(
            client=in_memory_api_client, simulation_id=sim_experiment.simulation_id
        )

        if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
            raise TypeError()

        num_loops = 0
        while current_status.status != JobStatus.COMPLETED and num_loops < 10:
            await asyncio.sleep(2)
            current_status = await get_simulation_status.asyncio(
                client=in_memory_api_client, simulation_id=sim_experiment.simulation_id
            )
            num_loops += 1

            if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
                raise TypeError()

        current_status = await get_simulation_status.asyncio(
            client=in_memory_api_client, simulation_id=sim_experiment.simulation_id
        )

        if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
            raise TypeError()

        assert current_status.status == JobStatus.COMPLETED

        results = await get_simulation_results_file.asyncio_detailed(
            client=in_memory_api_client, experiment_id=sim_experiment.experiment_id
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            experiment_results = temp_dir_path / Path("experiment_results.zip")
            with open(experiment_results, "wb") as results_file:
                results_file.write(results.content)
            simulation_fixtures.helper_test_sim_results(experiment_results, temp_dir_path)

    # response = await httpx_client.get("/version")
    # assert response.status_code == 200
    # data = response.json()
    # assert data == current_version
