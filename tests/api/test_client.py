import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from compose_api.api.client import Client
from compose_api.api.client.api.simulations import (
    execute_sedml,
    get_simulation_results_file,
    get_simulation_status,
    run_simulation,
)
from compose_api.api.client.models import (
    BodyExecuteSedml,
    HpcRun,
    HTTPValidationError,
    JobStatus,
    SimulationExperiment,
    ToolSuites,
)
from compose_api.api.client.models.body_run_simulation import BodyRunSimulation
from compose_api.api.client.types import File, Response
from compose_api.common.gateway.models import ServerMode
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.data_service import DataService
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import SimulationRequest, Simulator
from compose_api.simulation.simulation_service import SimulationServiceHpc
from compose_api.version import __version__
from tests.simulators.utils import assert_test_sim_results, check_experiment_run, test_dir

server_urls = [ServerMode.DEV, ServerMode.PROD]
current_version = __version__


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_sim_run(
    in_memory_api_client: Client,
    simulation_request: SimulationRequest,
    database_service: DatabaseServiceSQL,
    simulation_service_slurm: SimulationServiceHpc,
    job_monitor: JobMonitor,
    data_service: DataService,
    simulator: Simulator,
) -> None:
    assert simulation_request.omex_archive is not None
    with open(simulation_request.omex_archive, "rb") as f:
        sim_experiment = await run_simulation.asyncio(
            client=in_memory_api_client, body=BodyRunSimulation(uploaded_file=File(file_name=f.name, payload=f))
        )
        assert isinstance(sim_experiment, SimulationExperiment)

        current_status = await get_simulation_status.asyncio(
            client=in_memory_api_client, simulation_id=sim_experiment.simulation_database_id
        )

        if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
            raise TypeError()

        num_loops = 0
        while current_status.status != JobStatus.COMPLETED and num_loops < 10:
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
            report_csv_file = Path(os.path.join(test_dir, "fixtures/resources/report.csv"))
            assert_test_sim_results(experiment_results, report_csv_file, temp_dir_path)

    # response = await httpx_client.get("/version")
    # assert response.status_code == 200
    # data = response.json()
    # assert data == current_version


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_sedml_run(
    in_memory_api_client: Client,
    database_service: DatabaseServiceSQL,
    simulation_service_slurm: SimulationServiceHpc,
    job_monitor: JobMonitor,
    data_service: DataService,
    simulator: Simulator,
) -> None:
    omex_path = f"{test_dir}/resources/MODEL6615351360.3.omex"
    with open(omex_path, "rb") as f:
        for tool in ToolSuites:
            sim_experiment = await execute_sedml.asyncio(
                client=in_memory_api_client,
                body=BodyExecuteSedml(uploaded_file=File(file_name=f.name, payload=f)),
                tool_suite=tool,
            )

            results: Response[HTTPValidationError] = await check_experiment_run(
                sim_experiment=sim_experiment, in_memory_api_client=in_memory_api_client
            )

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_dir_path = Path(temp_dir)
                experiment_results = temp_dir_path / Path("experiment_results.zip")
                with open(experiment_results, "wb") as results_file:
                    results_file.write(results.content)
                report_csv_file = (
                    Path(os.path.join(test_dir, "resources/BIOMD0000000012.csv"))
                    if tool == ToolSuites.BASICO.value
                    else Path(os.path.join(test_dir, "resources/simulators/tellurium_sedml_parse.csv"))
                )
                assert_test_sim_results(experiment_results, report_csv_file, temp_dir_path, difference_tolerance=1e-3)
