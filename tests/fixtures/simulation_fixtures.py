import math
import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from zipfile import ZipFile

import numpy
import pytest_asyncio
from nats.aio.client import Client as NATSClient

from compose_api.btools.bsander.bsandr_utils.input_types import (
    ContainerizationEngine,
    ContainerizationTypes,
    ProgramArguments,
)
from compose_api.btools.bsander.execution import execute_bsander
from compose_api.btools.bsoil.introspect_package import introspect_package
from compose_api.common.hpc.models import SlurmJob
from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.db.database_service import DatabaseService
from compose_api.dependencies import (
    get_job_monitor,
    get_simulation_service,
    set_job_monitor,
    set_simulation_service,
)
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import JobStatus, JobType, SimulatorVersion
from compose_api.simulation.simulation_service import SimulationServiceHpc


@pytest_asyncio.fixture(scope="function")
async def simulation_service_slurm() -> AsyncGenerator[SimulationServiceHpc, None]:
    simulation_service = SimulationServiceHpc()
    saved_simulation_service = get_simulation_service()
    set_simulation_service(simulation_service)

    yield simulation_service

    await simulation_service.close()
    set_simulation_service(saved_simulation_service)


@pytest_asyncio.fixture(scope="function")
async def job_monitor(
    database_service: DatabaseService, slurm_service: SlurmService, nats_subscriber_client: NATSClient
) -> AsyncGenerator[JobMonitor, None]:
    job_service = JobMonitor(
        nats_client=nats_subscriber_client, database_service=database_service, slurm_service=slurm_service
    )
    saved_job_service = get_job_monitor()
    set_job_monitor(job_service)

    await job_service.subscribe_nats()
    await job_service.start_polling(interval_seconds=2)

    yield job_service

    await job_service.stop_polling()
    await job_service.close()
    set_job_monitor(saved_job_service)


@pytest_asyncio.fixture(scope="function")
async def simulator(database_service: DatabaseService) -> AsyncGenerator[SimulatorVersion, None]:
    omex_path = os.path.join(os.path.dirname(__file__), "resources/interesting-test.omex")
    with tempfile.TemporaryDirectory() as temp_dir:
        singularity_def, experiment_dep = execute_bsander(
            ProgramArguments(
                input_file_path=omex_path,
                output_dir=temp_dir,
                containerization_type=ContainerizationTypes.SINGLE,
                containerization_engine=ContainerizationEngine.APPTAINER,
                passlist_entries=["pypi::git+https://github.com/biosimulators/bspil-basico.git@initial_work"],
            )
        )

    package_outlines = introspect_package(experiment_dep)
    packages = []
    for outline in package_outlines:
        packages.append(await database_service.get_package_db().insert_package(outline))

    simulator = await database_service.get_simulator_db().insert_simulator(singularity_def, packages)
    fake_hpc_run = await database_service.get_hpc_db().insert_hpcrun(
        40, JobType.BUILD_CONTAINER, simulator.database_id, "jfldsjaljl"
    )
    await database_service.get_hpc_db().update_hpcrun_status(
        fake_hpc_run.database_id,
        SlurmJob(job_id=123, name="fds", account="foo", user_name="foo", job_state=JobStatus.COMPLETED),
    )
    yield simulator
    simulations = await database_service.get_simulator_db().list_simulations_that_use_simulator(
        simulator_id=simulator.database_id
    )
    for sim in simulations:
        hpc_run = await database_service.get_hpc_db().get_hpcrun_by_ref(sim.database_id, JobType.SIMULATION)
        if hpc_run is not None:
            await database_service.get_hpc_db().delete_hpcrun(hpcrun_id=hpc_run.database_id)
        await database_service.get_simulator_db().delete_simulation(simulation_id=sim.database_id)

    simulator_packages = await database_service.get_package_db().list_simulator_packages(
        simulator_id=simulator.database_id
    )
    for package in simulator_packages:
        for process in package.processes:
            await database_service.get_package_db().delete_bigraph_compute(process)
        for step in package.steps:
            await database_service.get_package_db().delete_bigraph_compute(step)
        await database_service.get_package_db().delete_bigraph_package(package)

    await database_service.get_hpc_db().delete_hpcrun(fake_hpc_run.database_id)
    await database_service.get_simulator_db().delete_simulator(simulator.database_id)


def assert_test_sim_results(archive_results: Path, temp_dir: Path) -> None:
    experiment_result = temp_dir / "report.csv"
    with ZipFile(archive_results) as zip_archive:
        zip_archive.extractall(temp_dir)
    test_dir = os.path.dirname(__file__).rsplit("/", 1)[0]
    report_csv_file = Path(os.path.join(test_dir, "fixtures/resources/report.csv"))
    experiment_numpy = numpy.genfromtxt(experiment_result, delimiter=",", dtype=object)
    report_numpy = numpy.genfromtxt(report_csv_file, delimiter=",", dtype=object)
    assert report_numpy.shape == experiment_numpy.shape
    r, c = report_numpy.shape
    for i in range(r):
        for j in range(c):
            report_val = report_numpy[i, j].decode("utf-8")
            experiment_val = experiment_numpy[i, j].decode("utf-8")
            try:
                f_report = float(report_val)
                f_exp = float(experiment_val)
                assert math.isclose(f_report, f_exp, rel_tol=0, abs_tol=1e-9)
            except ValueError:
                assert report_val == experiment_val  # Must be string portion of report then (columns)


# @pytest_asyncio.fixture
# async def experiment_file() -> File:
#     omex_path = Path(os.path.join(os.path.dirname(__file__), "resources/interesting-test.omex"))
#
#     return File(omex_path)
