import math
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from zipfile import ZipFile

import numpy
import pytest_asyncio
from nats.aio.client import Client as NATSClient

from compose_api.btools.bsander.bsandr_utils.input_types import ContainerizationFileRepr, ExperimentPrimaryDependencies
from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.db.database_service import DatabaseService
from compose_api.dependencies import (
    get_job_scheduler,
    get_simulation_service,
    set_job_scheduler,
    set_simulation_service,
)
from compose_api.simulation.job_scheduler import JobScheduler
from compose_api.simulation.models import JobType, SimulatorVersion
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
async def job_scheduler(
    database_service: DatabaseService, slurm_service: SlurmService, nats_subscriber_client: NATSClient
) -> AsyncGenerator[JobScheduler, None]:
    job_service = JobScheduler(
        nats_client=nats_subscriber_client, database_service=database_service, slurm_service=slurm_service
    )
    saved_job_service = get_job_scheduler()
    set_job_scheduler(job_service)

    await job_service.subscribe()
    await job_service.start_polling(interval_seconds=2)

    yield job_service

    await job_service.stop_polling()
    await job_service.close()
    set_job_scheduler(saved_job_service)


@pytest_asyncio.fixture(scope="function")
async def dummy_simulator(database_service: DatabaseService) -> AsyncGenerator[SimulatorVersion, None]:
    simulator = await database_service.insert_simulator(
        ContainerizationFileRepr(representation="singularity def"), ExperimentPrimaryDependencies(["pypi"], ["conda"])
    )
    yield simulator
    simulations = await database_service.list_simulations_that_use_simulator(simulator_id=simulator.database_id)
    for sim in simulations:
        hpc_run = await database_service.get_hpcrun_by_ref(sim.database_id, JobType.SIMULATION)
        if hpc_run is not None:
            await database_service.delete_hpcrun(hpcrun_id=hpc_run.database_id)
        await database_service.delete_simulation(simulation_id=sim.database_id)

    await database_service.delete_simulator(simulator.database_id)


def helper_test_sim_results(archive_results: Path, temp_dir: Path) -> None:
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
