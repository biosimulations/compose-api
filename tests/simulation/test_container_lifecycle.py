"""Pull and build a container through the production code paths, cheaply.

`test_simulation.py` covers the same two methods against the real simulator image, which
is large, slow to build, and only present on the cluster, so those tests are
`cluster_only` and run almost never. These use a busybox definition instead: the same
`download_container` and `build_container` code, the same sbatch template, the same
`--fakeroot` build and the same job monitoring, in seconds rather than minutes.

What they do not prove is that *the* simulator image builds. That stays with the
`cluster_only` tests. What they do prove is that the build machinery works at all, which
is the part that used to be untested everywhere.
"""

import asyncio
import random
import string
import time
import uuid

import pytest
from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

from compose_api.common.hpc.models import SlurmJob
from compose_api.common.ssh.ssh_service import SSHService
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.hpc_utils import (
    get_singularity_hash,
    get_slurm_singularity_container_file,
)
from compose_api.simulation.models import JobStatus, RemoteContainerImage, SimulatorVersion
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.fixtures.slurm_fixtures_backend import SlurmBackend

# Small enough that a build is seconds, real enough that %post runs and the runscript
# works, so a container that builds but cannot execute still fails.
PROBE_DEF = """\
Bootstrap: docker
From: busybox:latest

%post
    echo "compose-api build probe" > /built.txt

%runscript
    cat /built.txt
"""

# A tiny image that exists on any registry mirror the backend can reach.
PROBE_IMAGE_URL = "docker://busybox:latest"


def _probe_repr() -> ContainerizationFileRepr:
    # A unique definition per run, so two runs never race on the same remote .sif name.
    unique = PROBE_DEF + f"\n# {uuid.uuid4().hex}\n"
    return ContainerizationFileRepr(
        representation=unique, containerization_engine=ContainerizationEngine.APPTAINER
    )


async def _wait_for_db_status(
    database_service: DatabaseServiceSQL, hpcrun_id: int, expected: JobStatus, timeout_seconds: float
) -> None:
    """Wait for the monitor to record `expected`; it polls on its own schedule."""
    deadline = time.monotonic() + timeout_seconds
    last: JobStatus | None = None
    while time.monotonic() < deadline:
        run = await database_service.get_hpc_db().get_hpcrun(hpcrun_id)
        if run is not None:
            last = run.status
            if run.status == expected:
                return
        await asyncio.sleep(1)
    raise AssertionError(f"hpcrun {hpcrun_id} never reached {expected.value}; last status was {last}")


async def _wait_for_job(
    simulation_service_slurm: SimulationServiceHpc, slurmjobid: int, timeout_seconds: float
) -> SlurmJob:
    deadline = time.monotonic() + timeout_seconds
    job: SlurmJob | None = None
    while time.monotonic() < deadline:
        job = await simulation_service_slurm.get_slurm_job(slurmjobid=slurmjobid)
        if job is not None and job.is_done():
            return job
        await asyncio.sleep(2)
    state = job.job_state if job else "no job returned"
    raise AssertionError(f"slurm job {slurmjobid} did not finish within {timeout_seconds:.0f}s; last state {state}")


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_download_container_pulls_and_records_it(
    slurm_backend: SlurmBackend,
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    ssh_service: SSHService,
) -> None:
    """`download_container` pulls a real image over SSH and records it in the database."""
    container_def = _probe_repr()
    image = RemoteContainerImage(
        source_url=PROBE_IMAGE_URL,
        image_name_and_tag="busybox:latest",
        container_def=container_def,
        container_def_hash=get_singularity_hash(container_def),
        packages=None,
    )

    simulator_version = await simulation_service_slurm.download_container(image)
    try:
        assert simulator_version.container_def_hash == image.container_def_hash

        downloaded = await database_service.get_simulator_db().get_downloaded_simulator(
            simulator_id=simulator_version.database_id
        )
        assert downloaded is not None
        assert downloaded.source_url == PROBE_IMAGE_URL

        # The pull is the point: the .sif must actually be on the remote host.
        sif = get_slurm_singularity_container_file(singularity_hash=image.container_def_hash)
        return_code, _stdout, _stderr = await ssh_service.run_command(f"test -s {sif}")
        assert return_code == 0, f"{sif} is missing or empty on the backend"

        # And it must be a container, not just bytes.
        return_code, stdout, _stderr = await ssh_service.run_command(f"singularity exec {sif} echo EXEC_OK")
        assert return_code == 0
        assert "EXEC_OK" in stdout
    finally:
        await ssh_service.run_command(f"rm -f {get_slurm_singularity_container_file(image.container_def_hash)}")
        # The simulator row is left behind on purpose: `downloaded_containers` holds a
        # foreign key to it and there is no API to remove that row, so `delete_simulator`
        # raises. The Postgres fixture is a per-session container, so nothing leaks past
        # the run. Each test uses a unique definition hash, so rows never collide.


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_build_container_runs_a_fakeroot_build_to_completion(
    slurm_backend: SlurmBackend,
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    job_monitor: object,
    ssh_service: SSHService,
) -> None:
    """`build_container` submits the real sbatch template and the build succeeds.

    This is the path that writes `singularity build --fakeroot` into a job script, so it
    is also what proves the backend has a subordinate id range: without one the build
    fails with "no mapping entry found in /etc/subuid".
    """
    if not slurm_backend.can_build_singularity:
        pytest.skip(f"the {slurm_backend.kind} backend cannot build singularity images")

    container_def = _probe_repr()
    simulator: SimulatorVersion = await database_service.get_simulator_db().insert_simulator(container_def)
    random_str = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 - not security relevant

    hpc_run = await simulation_service_slurm.build_container(simulator, random_str=random_str)
    try:
        job = await _wait_for_job(simulation_service_slurm, hpc_run.slurmjobid, timeout_seconds=600)
        sif = get_slurm_singularity_container_file(singularity_hash=simulator.container_def_hash)
        if job.is_failed():
            _rc, log, _stderr = await ssh_service.run_command(
                f"tail -40 $(dirname {sif})/../htclogs/*{simulator.container_def_hash[:5]}*.out 2>/dev/null"
            )
            raise AssertionError(f"build job {hpc_run.slurmjobid} failed with {job.job_state}; log tail:\n{log}")

        await _wait_for_db_status(database_service, hpc_run.database_id, JobStatus.COMPLETED, timeout_seconds=60)

        # The built image must exist and run its %runscript, proving %post executed.
        return_code, stdout, _stderr = await ssh_service.run_command(f"singularity run {sif}")
        assert return_code == 0
        assert "compose-api build probe" in stdout
    finally:
        await ssh_service.run_command(
            f"rm -f {get_slurm_singularity_container_file(simulator.container_def_hash)}"
        )
        await database_service.get_hpc_db().delete_hpcrun(hpcrun_id=hpc_run.database_id)
        await database_service.get_simulator_db().delete_simulator(simulator_id=simulator.database_id)
