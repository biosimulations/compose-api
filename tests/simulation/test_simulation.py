import asyncio
import os
import random
import string
import tempfile
import time
from pathlib import Path

import pytest

from compose_api.common.hpc.models import SlurmJob
from compose_api.common.ssh.ssh_service import SSHService
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.hpc_utils import (
    get_correlation_id,
)
from compose_api.simulation.models import JobType, PBAllowList, SimulationRequest
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.fixtures import simulation_fixtures


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_simulate(
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    ssh_service: SSHService,
) -> None:
    # insert the latest commit into the database
    random_string = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
    simulation = await database_service.insert_simulation(sim_request=simulation_request, correlation_id=random_string)

    correlation_id = get_correlation_id(random_string=random_string)
    sim_slurmjobid = await simulation_service_slurm.submit_simulation_job(
        white_list=PBAllowList(allow_list=["pypi:bspil-basico"]),
        simulation=simulation,
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
    sim_slurmjob: SlurmJob | None = None
    while start_time + 60 > time.time():
        sim_slurmjob = await simulation_service_slurm.get_slurm_job_status(slurmjobid=sim_slurmjobid)
        if sim_slurmjob is not None and sim_slurmjob.is_done():
            break
        await asyncio.sleep(5)

    assert sim_slurmjob is not None
    assert sim_slurmjob.is_done()
    if sim_slurmjob.is_failed():
        raise AssertionError(
            f"Slurm job {sim_slurmjobid} failed with status: {sim_slurmjob.job_state}[ exit code: {sim_slurmjob.exit_code} ]"  # noqa: E501
        )
    assert sim_slurmjob.job_id == sim_slurmjobid

    remote_experiment_result = await simulation_service_slurm.get_slurm_job_result_path(slurmjobid=sim_slurmjobid)
    with tempfile.TemporaryDirectory(delete=False) as temp_dir:
        temp_dir_path = Path(temp_dir)
        archive_result = temp_dir_path / os.path.basename(remote_experiment_result)
        # SCP used because in test FS is not mounted
        await ssh_service.scp_download(archive_result, remote_experiment_result)
        simulation_fixtures.helper_test_sim_results(archive_result, temp_dir_path)


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_simulator_not_in_allowlist(
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
) -> None:
    # insert the latest commit into the database
    random_string = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
    simulation = await database_service.insert_simulation(sim_request=simulation_request, correlation_id=random_string)

    correlation_id = get_correlation_id(random_string=random_string)
    with pytest.raises(ValueError):
        await simulation_service_slurm.submit_simulation_job(
            white_list=PBAllowList(allow_list=["pypi:bspil"]),
            simulation=simulation,
            database_service=database_service,
            correlation_id=correlation_id,
        )
