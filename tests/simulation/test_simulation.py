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
from compose_api.simulation import handlers
from compose_api.simulation.hpc_utils import (
    get_experiment_id,
)
from compose_api.simulation.job_scheduler import JobMonitor
from compose_api.simulation.models import JobType, PBAllowList, SimulationRequest, SimulatorVersion
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.fixtures import simulation_fixtures


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_simulate(
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    ssh_service: SSHService,
    job_scheduler: JobMonitor,
    dummy_simulator: SimulatorVersion,
) -> None:
    # insert the latest commit into the database

    sim_experiement = await handlers.run_simulation(
        simulation_request=simulation_request,
        database_service=database_service,
        simulation_service_slurm=simulation_service_slurm,
        job_monitor=job_scheduler,
        background_tasks=None,
        pb_allow_list=None,
    )
    assert sim_experiement is not None

    hpcrun = await database_service.get_hpcrun_by_ref(sim_experiement.simulation.database_id, JobType.SIMULATION)
    assert hpcrun is not None
    assert hpcrun.job_type == JobType.SIMULATION
    assert hpcrun.sim_id == sim_experiement.simulation.database_id

    start_time = time.time()
    sim_slurmjob: SlurmJob | None = None
    while start_time + 60 > time.time():
        sim_slurmjob = await simulation_service_slurm.get_slurm_job_status(slurmjobid=hpcrun.slurmjobid)
        if sim_slurmjob is not None and sim_slurmjob.is_done():
            break
        await asyncio.sleep(5)

    assert sim_slurmjob is not None
    assert sim_slurmjob.is_done()
    if sim_slurmjob.is_failed():
        raise AssertionError(
            f"Slurm job {sim_slurmjob.job_id} failed with status: {sim_slurmjob.job_state}[ exit code: {sim_slurmjob.exit_code} ]"  # noqa: E501
        )
    assert sim_slurmjob.job_id == hpcrun.slurmjobid

    remote_experiment_result = await simulation_service_slurm.get_slurm_job_result_path(slurmjobid=sim_slurmjob.job_id)
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
    job_scheduler: JobMonitor,
    dummy_simulator: SimulatorVersion,
) -> None:
    # insert the latest commit into the database
    experiement_id = get_experiment_id(dummy_simulator, "".join(random.choices(string.hexdigits, k=7)))  # noqa: S311 doesn't need to be secure

    simulation = await database_service.insert_simulation(
        sim_request=simulation_request, experiment_id=experiement_id, simulator_version=dummy_simulator
    )

    with pytest.raises(ValueError):
        await handlers.run_simulation(
            simulation_request,
            database_service,
            simulation_service_slurm,
            job_monitor=job_scheduler,
            background_tasks=None,
            pb_allow_list=PBAllowList(allow_list=["pypi:bspil"]),
        )
        await simulation_service_slurm.submit_simulation_job(
            simulation=simulation,
            database_service=database_service,
            experiment_id=experiement_id,
        )
