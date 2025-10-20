import os
import tempfile
from pathlib import Path

import pytest

from compose_api.api.client import Client
from compose_api.api.client.api.simulators import run_tellurium
from compose_api.api.client.models import BodyRunTellurium
from compose_api.api.client.types import File
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.data_service import DataService
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import Simulator
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.simulators.utils import assert_test_sim_results, check_experiment_run, test_dir


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_tellurium(
    in_memory_api_client: Client,
    database_service: DatabaseServiceSQL,
    simulation_service_slurm: SimulationServiceHpc,
    job_monitor: JobMonitor,
    data_service: DataService,
    simulator: Simulator,
) -> None:
    tellurium_sbml = os.path.join(test_dir, "resources/simulators/tellurium.sbml")
    with open(tellurium_sbml, "rb") as f:
        sim_experiment = await run_tellurium.asyncio(
            client=in_memory_api_client,
            start_time=0,
            end_time=10,
            num_data_points=51,
            body=BodyRunTellurium(sbml=File(file_name="tellurium.sbml", payload=f)),
        )

        results = await check_experiment_run(sim_experiment=sim_experiment, in_memory_api_client=in_memory_api_client)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            experiment_results = temp_dir_path / Path("experiment_results.zip")
            with open(experiment_results, "wb") as results_file:
                results_file.write(results.content)
            assert_test_sim_results(
                archive_results=experiment_results,
                expected_csv_path=Path(f"{test_dir}/resources/simulators/tellurium_report.csv"),
                temp_dir=temp_dir_path,
            )
