import asyncio
import os

import pytest

from compose_api.api.client import Client
from compose_api.api.client.api.curated import run_copasi
from compose_api.api.client.api.results import get_simulations_status_batch
from compose_api.api.client.models import BodyRunCopasi, HpcRun, JobStatus, SimulationExperiment
from compose_api.api.client.types import File
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseService, DatabaseServiceSQL
from compose_api.simulation.data_service import DataService
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import JobType, SimulationRequest, Simulator, SimulatorVersion
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.simulators.utils import get_results_and_compare_copasi, test_dir


@pytest.mark.asyncio
async def test_get_simulations_status_batch(
    in_memory_api_client: Client,
    database_service: DatabaseService,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    sim_a = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request,
        experiment_id="test_batch_experiment_a",
        simulator_version=simulator,
    )
    sim_b = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request,
        experiment_id="test_batch_experiment_b",
        simulator_version=simulator,
    )

    hpcrun_a = await database_service.get_hpc_db().insert_hpcrun(
        slurmjobid=1001,
        job_type=JobType.SIMULATION,
        ref_id=sim_a.database_id,
        correlation_id="corr_a",
    )
    hpcrun_b = await database_service.get_hpc_db().insert_hpcrun(
        slurmjobid=1002,
        job_type=JobType.SIMULATION,
        ref_id=sim_b.database_id,
        correlation_id="corr_b",
    )

    try:
        response = await get_simulations_status_batch.asyncio_detailed(
            client=in_memory_api_client, body=[sim_a.database_id, sim_b.database_id]
        )

        assert response.status_code == 200
        results = response.parsed
        assert isinstance(results, list)
        assert len(results) == 2

        returned_sim_ids = {r.sim_id for r in results}
        assert sim_a.database_id in returned_sim_ids
        assert sim_b.database_id in returned_sim_ids

        returned_slurm_ids = {r.slurmjobid for r in results}
        assert hpcrun_a.slurmjobid in returned_slurm_ids
        assert hpcrun_b.slurmjobid in returned_slurm_ids
    finally:
        await database_service.get_hpc_db().delete_hpcrun(hpcrun_a.database_id)
        await database_service.get_hpc_db().delete_hpcrun(hpcrun_b.database_id)
        await database_service.get_simulator_db().delete_simulation(sim_a.database_id)
        await database_service.get_simulator_db().delete_simulation(sim_b.database_id)


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_batch_status_after_copasi_runs(
    in_memory_api_client: Client,
    database_service: DatabaseServiceSQL,
    simulation_service_slurm: SimulationServiceHpc,
    job_monitor: JobMonitor,
    data_service: DataService,
    simulator: Simulator,
) -> None:
    copasi_sbml = os.path.join(test_dir, "fixtures/resources/copasi.sbml")
    experiments: list[SimulationExperiment] = []
    with open(copasi_sbml, "rb") as f:
        for _ in range(2):
            f.seek(0)
            sim_experiment = await run_copasi.asyncio(
                client=in_memory_api_client,
                start_time=0,
                duration=10,
                num_data_points=51,
                body=BodyRunCopasi(sbml=File(file_name="copasi.sbml", payload=f)),
            )
            assert isinstance(sim_experiment, SimulationExperiment)
            experiments.append(sim_experiment)

    sim_ids = [exp.simulation_database_id for exp in experiments]
    terminal_statuses = {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.TIMEOUT,
        JobStatus.OUT_OF_MEMORY,
    }
    num_loops = 0

    results: list[HpcRun] = []
    while num_loops < 60:
        response = await get_simulations_status_batch.asyncio_detailed(
            client=in_memory_api_client,
            body=sim_ids,
        )
        assert response.status_code == 200
        assert isinstance(response.parsed, list)
        results = response.parsed
        if all(r.status in terminal_statuses for r in results):
            break

        await asyncio.sleep(2)
        num_loops += 1

    assert len(results) == len(experiments)

    for result in results:
        assert result.sim_id in sim_ids
        assert result.status == JobStatus.COMPLETED, f"Simulation {result.sim_id} ended with status {result.status}"
        await get_results_and_compare_copasi(api_client=in_memory_api_client, sim_id=result.sim_id)
