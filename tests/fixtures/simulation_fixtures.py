import os
import tempfile
from collections.abc import AsyncGenerator

import pytest_asyncio
from nats.aio.client import Client as NATSClient

from compose_api.btools.bsander.bsandr_utils.input_types import (
    ContainerizationEngine,
    ContainerizationTypes,
    ProgramArguments,
)
from compose_api.btools.bsander.execution import execute_bsander
from compose_api.btools.bsoil.introspect_package import introspect_package
from compose_api.common.gateway.utils import allow_list
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
                passlist_entries=allow_list,
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
    await database_service.get_hpc_db().delete_hpcrun(fake_hpc_run.database_id)
    await database_service.get_simulator_db().delete_simulator(simulator.database_id)

    for package in simulator_packages:
        for process in package.processes:
            await database_service.get_package_db().delete_bigraph_compute(process)
        for step in package.steps:
            await database_service.get_package_db().delete_bigraph_compute(step)
        await database_service.get_package_db().delete_bigraph_package(package)


# @pytest_asyncio.fixture
# async def experiment_file() -> File:
#     omex_path = Path(os.path.join(os.path.dirname(__file__), "resources/interesting-test.omex"))
#
#     return File(omex_path)
