from collections.abc import AsyncGenerator

import pytest_asyncio
from nats.aio.client import Client as NATSClient

from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.db.database_service import DatabaseService
from compose_api.dependencies import (
    get_job_scheduler,
    get_simulation_service,
    set_job_scheduler,
    set_simulation_service,
)
from compose_api.simulation.job_scheduler import JobScheduler
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


# @pytest_asyncio.fixture
# async def experiment_file() -> File:
#     omex_path = Path(os.path.join(os.path.dirname(__file__), "resources/interesting-test.omex"))
#
#     return File(omex_path)
