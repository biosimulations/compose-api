import asyncio
import random
import string
import time

import pytest

from biosim_api.config import get_settings
from biosim_api.simulation.database_service import DatabaseServiceSQL
from biosim_api.simulation.hpc_utils import get_correlation_id
from biosim_api.simulation.models import JobType, SimulationRequest, SimulatorVersion
from biosim_api.simulation.simulation_service import SimulationServiceHpc


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_simulate(simulation_service_slurm: SimulationServiceHpc, database_service: DatabaseServiceSQL) -> None:
    # insert the latest commit into the database
    simulator: SimulatorVersion = await database_service.insert_simulator(
        git_commit_hash="abc", git_repo_url="abc", git_branch="abc"
    )

    simulation_request = SimulationRequest(
        simulator=simulator,
        variant_config={"named_parameters": {"param1": 0.5, "param2": 0.5}},
    )
    simulation = await database_service.insert_simulation(sim_request=simulation_request)

    random_string = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311. doesn't need to be secure
    correlation_id = get_correlation_id(simulation=simulation, random_string=random_string)
    sim_slurmjobid = await simulation_service_slurm.submit_simulation_job(
        simulation=simulation,
        simulator_version=simulator,
        database_service=database_service,
        correlation_id=correlation_id,
    )
    assert sim_slurmjobid is not None

    hpcrun = await database_service.insert_hpcrun(
        slurmjobid=sim_slurmjobid,
        job_type=JobType.SIMULATION,
        ref_id=simulation.database_id,
        correlation_id=correlation_id,
    )
    assert hpcrun is not None
    assert hpcrun.slurmjobid == sim_slurmjobid
    assert hpcrun.job_type == JobType.SIMULATION
    assert hpcrun.ref_id == simulation.database_id

    start_time = time.time()
    while start_time + 60 > time.time():
        sim_slurmjob = await simulation_service_slurm.get_slurm_job_status(slurmjobid=sim_slurmjobid)
        if sim_slurmjob is not None and sim_slurmjob.is_done():
            break
        await asyncio.sleep(5)

    assert sim_slurmjob is not None
    assert sim_slurmjob.is_done()
    assert sim_slurmjob.job_id == sim_slurmjobid
