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
from compose_api.btools.bsander.bsandr_utils.input_types import (
    ProgramArguments,
    ContainerizationTypes,
    ContainerizationEngine
)
from compose_api.btools.bsander.execution import execute_bsander
from compose_api.simulation.job_scheduler import JobMonitor
from compose_api.simulation.models import JobType, PBAllowList, SimulationRequest, SimulatorVersion
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.fixtures import simulation_fixtures


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_build_simulator(
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    ssh_service: SSHService,
    job_scheduler: JobMonitor,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        singularity_def, experiment_dep = execute_bsander(
            ProgramArguments(
                input_file_path=str(simulation_request.omex_archive),
                output_dir=temp_dir,
                containerization_type=ContainerizationTypes.SINGLE,
                containerization_engine=ContainerizationEngine.APPTAINER,
                passlist_entries=["pypi::git+https://github.com/biosimulators/bspil-basico.git@initial_work"],
            )
        )
    simulator = await database_service.insert_simulator(singularity_def, experiment_dep)
    start_time = time.time()
    slurm_job_id = await simulation_service_slurm.build_container(simulator)

    slurm_build_job: SlurmJob | None = None
    while start_time + (60 * 20) > time.time():  # No longer than twenty mins
        slurm_build_job = await simulation_service_slurm.get_slurm_job_status(slurmjobid=slurm_job_id)
        if slurm_build_job is not None and slurm_build_job.is_done():
            break
        await asyncio.sleep(30)

    assert slurm_build_job is not None
    assert slurm_build_job.is_done()
    assert not slurm_build_job.is_failed()


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_simulate_pypi(
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    simulation_request_pypi: SimulationRequest,
    ssh_service: SSHService,
    job_scheduler: JobMonitor,
    simulator: SimulatorVersion,
) -> None:
    # insert the latest commit into the database

    sim_experiment = await handlers.run_simulation(
        simulation_request=simulation_request_pypi,
        database_service=database_service,
        simulation_service_slurm=simulation_service_slurm,
        job_monitor=job_scheduler,
        background_tasks=None,
        pb_allow_list=PBAllowList(
            allow_list=["pypi::git+https://github.com/biosimulators/bspil-basico.git@initial_work"]
        ),
    )
    assert sim_experiment is not None

    hpcrun = await database_service.get_hpcrun_by_ref(sim_experiment.simulation_id, JobType.SIMULATION)
    assert hpcrun is not None
    assert hpcrun.job_type == JobType.SIMULATION
    assert hpcrun.sim_id == sim_experiment.simulation_id

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
async def test_simulate_conda(
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    simulation_request_conda: SimulationRequest,
    ssh_service: SSHService,
    job_scheduler: JobMonitor,
    simulator: SimulatorVersion,
) -> None:
    # insert the latest commit into the database

    sim_experiement = await handlers.run_simulation(
        simulation_request=simulation_request_conda,
        database_service=database_service,
        simulation_service_slurm=simulation_service_slurm,
        job_monitor=job_scheduler,
        background_tasks=None,
        pb_allow_list=PBAllowList(
            allow_list=["conda::git+https://github.com/CodeByDrescher/multiscale-actin.git"]
        ),
    )
    assert sim_experiement is not None

    hpcrun = await database_service.get_hpcrun_by_ref(sim_experiement.simulation_id, JobType.SIMULATION)
    assert hpcrun is not None
    assert hpcrun.job_type == JobType.SIMULATION
    assert hpcrun.sim_id == sim_experiement.simulation_id

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
    simulation_request_pypi: SimulationRequest,
    job_scheduler: JobMonitor,
    simulator: SimulatorVersion,
) -> None:
    # insert the latest commit into the database
    experiement_id = get_experiment_id(simulator, "".join(random.choices(string.hexdigits, k=7)))  # noqa: S311 doesn't need to be secure

    simulation = await database_service.insert_simulation(
        sim_request=simulation_request_pypi, experiment_id=experiement_id, simulator_version=simulator
    )

    with pytest.raises(ValueError):
        await handlers.run_simulation(
            simulation_request_pypi,
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
