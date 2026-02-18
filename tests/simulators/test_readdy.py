import os

import pytest

from compose_api.api.client import Client
from compose_api.api.client.api.simulation import run_simulation
from compose_api.api.client.models import BodyRunSimulation
from compose_api.api.client.types import File
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.data_service import DataService
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import Simulator
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.simulators.utils import check_experiment_run


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_readdy(
    in_memory_api_client: Client,
    database_service: DatabaseServiceSQL,
    simulation_service_slurm: SimulationServiceHpc,
    job_monitor: JobMonitor,
    data_service: DataService,
    simulator: Simulator,
) -> None:
    copasi_sbml = os.path.join(os.path.dirname(__file__).rsplit("/", 1)[0], "fixtures/resources/readdy.omex")
    with open(copasi_sbml, "rb") as f:
        sim_experiment = await run_simulation.asyncio(
            client=in_memory_api_client,
            interval_time=3.0,
            body=BodyRunSimulation(uploaded_file=File(file_name="readdy.omex", payload=f)),
        )

        results = await check_experiment_run(
            sim_experiment=sim_experiment, in_memory_api_client=in_memory_api_client, seconds_to_wait=5 * 60
        )

    result_path = "/Users/evalencia/Desktop/readdy.zip"
    with open(result_path, "wb") as f:
        f.write(results.content)
