import json
import os
import tempfile
import zipfile

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
from tests.simulators.utils import (
    check_experiment_run,
    get_results_and_compare_copasi,
)

test_pbg = {
    "state": {
        "time_course": {
            "_type": "step",
            "address": "local:pbsim_common.simulators.copasi_process.CopasiUTCStep",
            "config": {
                "model_source": "interesting.sbml",
                "sim_start_time": 0,
                "time": 10,
                "n_points": 51,
                "output_dir": "/experiment/output",
            },
            "interval": 1.0,
            "inputs": {},
            "outputs": {},
        }
    }
}


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_copasi_batch(
    in_memory_api_client: Client,
    database_service: DatabaseServiceSQL,
    simulation_service_slurm: SimulationServiceHpc,
    job_monitor: JobMonitor,
    data_service: DataService,
    simulator: Simulator,
) -> None:
    copasi_sbml = os.path.join(os.path.dirname(__file__).rsplit("/", 1)[0], "fixtures/resources/copasi.sbml")
    with tempfile.TemporaryDirectory() as tmpdir:
        pbg_path = os.path.join(tmpdir, "input.pbg")
        zip_path = os.path.join(tmpdir, "input.zip")
        with open(pbg_path, "w") as f:
            json.dump(test_pbg, f)
        with zipfile.ZipFile(zip_path, "w") as zip_ref:
            zip_ref.write(copasi_sbml, "interesting.sbml")
            zip_ref.write(pbg_path, "input.pbg")

        with open(zip_path, "rb") as f:
            sim_experiment = await run_simulation.asyncio(
                client=in_memory_api_client,
                body=BodyRunSimulation(uploaded_file=File(file_name="interesting.omex", payload=f)),
                batch_submission=True,
            )

            results = await check_experiment_run(
                sim_experiment=sim_experiment, in_memory_api_client=in_memory_api_client
            )
            await get_results_and_compare_copasi(api_client=in_memory_api_client, file_result=results)
