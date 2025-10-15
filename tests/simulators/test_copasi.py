import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from compose_api.api.client import Client
from compose_api.api.client.api.simulations import get_simulation_results_file, get_simulation_status
from compose_api.api.client.api.simulators import run_copasi
from compose_api.api.client.models import BodyRunCopasi, HpcRun, JobStatus, SimulationExperiment
from compose_api.api.client.types import File
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.data_service import DataService
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import Simulator
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.fixtures import simulation_fixtures


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
        assert isinstance(sim_experiment, SimulationExperiment)

        current_status = await get_simulation_status.asyncio(
            client=in_memory_api_client, simulation_id=sim_experiment.simulation_database_id
        )

        if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
            raise TypeError()

        num_loops = 0
        while current_status.status != JobStatus.COMPLETED and num_loops < 30:
            await asyncio.sleep(2)
            current_status = await get_simulation_status.asyncio(
                client=in_memory_api_client, simulation_id=sim_experiment.simulation_database_id
            )
            num_loops += 1

            if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
                raise TypeError()

        current_status = await get_simulation_status.asyncio(
            client=in_memory_api_client, simulation_id=sim_experiment.simulation_database_id
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
            simulation_fixtures.assert_test_sim_results(experiment_results, temp_dir_path)
