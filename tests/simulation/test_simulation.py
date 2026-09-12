import asyncio
import os
import random
import string
import tempfile
import time
from pathlib import Path

import pytest
from pbest.containerization.container_constructor import _default_registry_deps, generate_container_def_file
from pbest.utils.input_types import (
    ContainerizationEngine,
    ContainerizationFileRepr,
)

from compose_api.common.gateway.utils import allow_list
from compose_api.common.hpc.models import SlurmJob
from compose_api.common.ssh.ssh_service import SSHService
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation import handlers
from compose_api.simulation.hpc_utils import (
    _namespace_path,
    get_singularity_hash,
    get_slurm_singularity_container_file,
)
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
from tests.fixtures.simulation_fixtures import PRODUCTION_SIMULATOR_DEF_HASH
from tests.fixtures.slurm_fixtures_backend import SlurmBackend
from tests.simulators.utils import assert_test_sim_results, test_dir

# Small, multi-arch and public, so it pulls quickly on either backend and on either CPU
# architecture. It stands in for a simulator image only to exercise the download path.
PULLABLE_PROBE_IMAGE = "docker://busybox:latest"


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_download_simulator(
    slurm_backend: SlurmBackend,
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    ssh_service: SSHService,
) -> None:
    """`download_container` pulls a real image over SSH and records it in the database.

    The identity is the real pbest-generated definition and its hash, but the image pulled
    is a small public one, for two reasons. No simulator image is published under an
    account we control: the previous location was a personal Docker Hub account belonging
    to someone who has left, and it is not to be used. And the tag for the current pbest
    pin does not exist there in any case, so the download this test is named for cannot be
    performed at all until an image is published. What it does still prove is the
    mechanism and the database recording, against the real production code path.
    """
    container_rep = generate_container_def_file(_default_registry_deps(), ContainerizationEngine.APPTAINER)
    image = RemoteContainerImage(
        source_url=PULLABLE_PROBE_IMAGE,
        image_name_and_tag=PULLABLE_PROBE_IMAGE.removeprefix("docker://"),
        container_def=container_rep,
        container_def_hash=get_singularity_hash(container_rep),
        packages=None,
    )
    simulator_version = await simulation_service_slurm.download_container(image)
    assert simulator_version is not None

    # The pull is the point. Asserting only on database rows would let a download that
    # wrote nothing pass, which is how this test could previously have gone green against
    # an image that does not exist.
    sif = get_slurm_singularity_container_file(singularity_hash=image.container_def_hash)
    return_code, _stdout, _stderr = await ssh_service.run_command(f"test -s {sif}")
    assert return_code == 0, f"{sif} is missing or empty on the {slurm_backend.kind} backend"
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

    await ssh_service.run_command(f"rm -f {sif}")


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_build_simulator(
    slurm_backend: SlurmBackend,
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    ssh_service: SSHService,
    job_monitor: JobMonitor,
    production_simulator_def: ContainerizationFileRepr,
) -> None:
    """Build a real deployed simulator definition through the production build path.

    The definition is copied verbatim from the live deployment, so this exercises
    `singularity build --fakeroot` against content a deployment actually produced rather
    than against something a test invented. It is the smallest of the definitions
    published there, which is why it is affordable on every pull request: about 70 seconds
    to a 594 MB image on the containerised cluster, against minutes and 1.3 GB for the
    versions that solve a full conda environment.

    The package introspection the previous version did is dropped. It exercised pbest's
    default dependency set, not the build, and it tied this test to a pin that changes.
    """
    if not slurm_backend.can_build_singularity:
        pytest.skip(f"the {slurm_backend.kind} backend cannot build singularity images")

    # Guards the fixture: `get_singularity_hash` is an md5 over the exact bytes, so an
    # edit to the .def file would otherwise silently change what is being built.
    assert get_singularity_hash(production_simulator_def) == PRODUCTION_SIMULATOR_DEF_HASH

    simulator = await database_service.get_simulator_db().insert_simulator(production_simulator_def)
    random_string_7_hex = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
    hpc_run = await simulation_service_slurm.build_container(simulator, random_str=random_string_7_hex)

    sif = get_slurm_singularity_container_file(singularity_hash=simulator.container_def_hash)
    try:
        deadline = time.monotonic() + 20 * 60
        slurm_build_job: SlurmJob | None = None
        while time.monotonic() < deadline:
            slurm_build_job = await simulation_service_slurm.get_slurm_job(slurmjobid=hpc_run.slurmjobid)
            if slurm_build_job is not None and slurm_build_job.is_done():
                break
            await asyncio.sleep(5)

        assert slurm_build_job is not None, f"build job {hpc_run.slurmjobid} never appeared"
        assert slurm_build_job.is_done(), f"build job did not finish; last state {slurm_build_job.job_state}"
        if slurm_build_job.is_failed():
            _rc, log, _err = await ssh_service.run_command(
                f"tail -40 {_namespace_path()}/htclogs/*{simulator.container_def_hash[:5]}*.out 2>/dev/null"
            )
            raise AssertionError(f"build failed with {slurm_build_job.job_state}; log tail:\n{log}")

        # The scheduler reporting the job done and the monitor recording it are separate
        # events; the monitor polls on its own schedule, so this must wait rather than
        # assert once.
        db_deadline = time.monotonic() + 120
        db_view_of_run = None
        while time.monotonic() < db_deadline:
            db_view_of_run = await database_service.get_hpc_db().get_hpcrun(hpc_run.database_id)
            if db_view_of_run is not None and db_view_of_run.status == JobStatus.COMPLETED:
                break
            await asyncio.sleep(2)
        assert db_view_of_run is not None
        assert db_view_of_run.status == JobStatus.COMPLETED, (
            f"the monitor never recorded the build as completed; last status {db_view_of_run.status}"
        )

        # The artifact is the point. A job that exits zero without producing an image
        # would otherwise pass, and the image must be runnable, not merely present.
        return_code, _stdout, _stderr = await ssh_service.run_command(f"test -s {sif}")
        assert return_code == 0, f"{sif} was not produced by the build"
        return_code, stdout, _stderr = await ssh_service.run_command(
            f"singularity exec {sif} python3 -c 'import bsew; print(\"BSEW_OK\")'"
        )
        assert return_code == 0 and "BSEW_OK" in stdout, "the built image does not run its installed package"
    finally:
        await ssh_service.run_command(f"rm -f {sif}")
        await database_service.get_hpc_db().delete_hpcrun(hpcrun_id=hpc_run.database_id)
        await database_service.get_simulator_db().delete_simulator(simulator_id=simulator.database_id)


@pytest.mark.slurm
@pytest.mark.cluster_only
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
