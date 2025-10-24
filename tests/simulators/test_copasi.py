import os
import tempfile
from pathlib import Path

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
from tests.simulators.utils import assert_test_sim_results, check_experiment_run, test_dir


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

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            experiment_results = temp_dir_path / Path("experiment_results.zip")
            with open(experiment_results, "wb") as results_file:
                results_file.write(results.content)
            report_csv_file = Path(os.path.join(test_dir, "fixtures/resources/report.csv"))
            assert_test_sim_results(
                archive_results=experiment_results, expected_csv_path=report_csv_file, temp_dir=temp_dir_path
            )
