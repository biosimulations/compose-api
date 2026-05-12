import asyncio
import os
import random
import string
import tempfile
import time
from pathlib import Path

import pytest
from pbest.containerization.container_constructor import _default_experiment_deps, generate_container_def_file
from pbest.utils.input_types import (
    ContainerizationEngine,
)

from compose_api.api.introspect_package import introspect_package
from compose_api.common.gateway.utils import allow_list
from compose_api.common.hpc.models import SlurmJob
from compose_api.common.ssh.ssh_service import SSHService
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation import handlers
from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import (
    JobStatus,
    JobType,
    PBAllowList,
    RemoteContainerImage,
    SimulationRequest,
    SimulatorVersion,
)
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.fixtures.mocks import TestBackgroundTask
from tests.simulators.utils import assert_test_sim_results, test_dir


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_download_simulator(
    simulation_service_slurm: SimulationServiceHpc, database_service: DatabaseServiceSQL
) -> None:
    container_rep = generate_container_def_file(_default_experiment_deps(), ContainerizationEngine.APPTAINER)
    image = RemoteContainerImage(
        source_url=f"docker://ezqvalencia/registry_env:{get_singularity_hash(container_rep)}",
        image_name_and_tag="ezqvalencia/registry_env",
        container_def=container_rep,
        container_def_hash=get_singularity_hash(container_rep),
        packages=None,
    )
    simulator_version = await simulation_service_slurm.download_container(image)
    assert simulator_version is not None
    saved_simulator_version = await database_service.get_simulator_db().get_simulator(
        simulator_id=simulator_version.database_id
    )
    assert saved_simulator_version is not None
    assert saved_simulator_version.container_def_hash == get_singularity_hash(container_rep)
    assert saved_simulator_version.container_def.representation == container_rep.representation

    downloaded_image = await database_service.get_simulator_db().get_downloaded_simulator(
        simulator_id=simulator_version.database_id
    )
    assert downloaded_image is not None
    assert downloaded_image.image_name_and_tag == image.image_name_and_tag
    assert downloaded_image.container_def_hash == get_singularity_hash(container_rep)
    assert downloaded_image.source_url == image.source_url


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_build_simulator(
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    ssh_service: SSHService,
    job_monitor: JobMonitor,
) -> None:
    singularity_def = generate_container_def_file(_default_experiment_deps(), ContainerizationEngine.APPTAINER)
    experiment_dep = _default_experiment_deps()
    package_outlines = introspect_package(experiment_dep)
    packages = []
    for outline in package_outlines:
        packages.append(await database_service.get_package_db().insert_package(outline))
    simulator = await database_service.get_simulator_db().insert_simulator(singularity_def, packages)
    start_time = time.time()
    random_string_7_hex = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
    hpc_run = await simulation_service_slurm.build_container(simulator, random_str=random_string_7_hex)

    slurm_build_job: SlurmJob | None = None
    while start_time + (60 * 20) > time.time():  # No longer than twenty mins
        slurm_build_job = await simulation_service_slurm.get_slurm_job(slurmjobid=hpc_run.slurmjobid)
        if slurm_build_job is not None and slurm_build_job.is_done():
            break
        await asyncio.sleep(30)

    db_view_of_run = await database_service.get_hpc_db().get_hpcrun(hpc_run.database_id)

    assert slurm_build_job is not None
    assert slurm_build_job.is_done()
    assert not slurm_build_job.is_failed()
    assert db_view_of_run is not None
    assert db_view_of_run.status == JobStatus.COMPLETED

    await database_service.get_hpc_db().delete_hpcrun(hpcrun_id=hpc_run.database_id)
    await database_service.get_simulator_db().delete_simulator(simulator_id=simulator.database_id)

    for p in packages:
        for s in p.steps:
            await database_service.get_package_db().delete_bigraph_compute(s)
        for process in p.processes:
            await database_service.get_package_db().delete_bigraph_compute(process)
        await database_service.get_package_db().delete_bigraph_package(p)


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_simulate(
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    ssh_service: SSHService,
    job_monitor: JobMonitor,
    simulator: SimulatorVersion,
) -> None:
    # insert the latest commit into the database

    test_bg_tasks = TestBackgroundTask()

    sim_experiement = await handlers.run_simulation(
        simulation_request=simulation_request,
        database_service=database_service,
        simulation_service_slurm=simulation_service_slurm,
        job_monitor=job_monitor,
        background_tasks=test_bg_tasks,
        pb_allow_list=PBAllowList(allow_list=allow_list),
    )
    assert sim_experiement is not None
    await test_bg_tasks.call_tasks()

    hpcrun = await database_service.get_hpc_db().get_hpcrun_by_ref(
        sim_experiement.simulation_database_id, JobType.SIMULATION
    )
    assert hpcrun is not None
    assert hpcrun.job_type == JobType.SIMULATION
    assert hpcrun.sim_id == sim_experiement.simulation_database_id

    start_time = time.time()
    sim_slurmjob: SlurmJob | None = None
    while start_time + 60 > time.time():
        sim_slurmjob = await simulation_service_slurm.get_slurm_job(slurmjobid=hpcrun.slurmjobid)
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
        report_csv_file = Path(os.path.join(test_dir, "fixtures/resources/report.csv"))
        assert_test_sim_results(archive_result, report_csv_file, temp_dir_path, difference_tolerance=1e-4)


# @pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
# @pytest.mark.asyncio
# async def test_simulator_not_in_allowlist(
#     simulation_service_slurm: SimulationServiceHpc,
#     database_service: DatabaseServiceSQL,
#     simulation_request: SimulationRequest,
#     job_monitor: JobMonitor,
#     simulator: SimulatorVersion,
# ) -> None:
#     # insert the latest commit into the database
#     test_bg_tasks = TestBackgroundTask()
#     experiement_id = get_experiment_id(simulator, "".join(random.choices(string.hexdigits, k=7)))
#
#     simulation = await database_service.get_simulator_db().insert_simulation(
#         sim_request=simulation_request, experiment_id=experiement_id, simulator_version=simulator
#     )
#
#     print(f"Reimplement allow list in the future: {allow_list}")

# with pytest.raises(ValueError):
#     await handlers.run_simulation(
#         simulation_request,
#         database_service,
#         simulation_service_slurm,
#         job_monitor=job_monitor,
#         background_tasks=test_bg_tasks,
#         pb_allow_list=PBAllowList(allow_list=["pypi:bspil"]),
#     )
#     await test_bg_tasks.call_tasks()
#     await simulation_service_slurm.submit_simulation_job(
#         simulation=simulation,
#         experiment_id=experiement_id,
#     )
