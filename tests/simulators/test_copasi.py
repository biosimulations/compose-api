import os

import pytest

from compose_api.api.client import Client
from compose_api.api.client.api.curated import run_copasi
from compose_api.api.client.models import BodyRunCopasi
from compose_api.api.client.types import File
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.data_service import DataService
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import Simulator
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.simulators.utils import (
    check_experiment_run,
    get_results_and_compare_copasi,
)


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_copasi(
    in_memory_api_client: Client,
    database_service: DatabaseServiceSQL,
    simulation_service_slurm: SimulationServiceHpc,
    job_monitor: JobMonitor,
    data_service: DataService,
    simulator: Simulator,
) -> None:
    copasi_sbml = os.path.join(os.path.dirname(__file__).rsplit("/", 1)[0], "fixtures/resources/copasi.sbml")
    with open(copasi_sbml, "rb") as f:
        sim_experiment = await run_copasi.asyncio(
            client=in_memory_api_client,
            start_time=0,
            duration=10,
            num_data_points=51,
            body=BodyRunCopasi(sbml=File(file_name="copasi.sbml", payload=f)),
        )

        results = await check_experiment_run(sim_experiment=sim_experiment, in_memory_api_client=in_memory_api_client)
        await get_results_and_compare_copasi(api_client=in_memory_api_client, file_result=results)
