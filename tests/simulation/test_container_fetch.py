"""A simulator's container is fetched once, however many submissions arrive while it is fetched.

Every submission used to fetch the image again: the download record was attached to a new simulator
row, so the lookup by the submission's simulator id never found it. Each fetch wrote the .sif over the
file that earlier submissions' jobs were mounting, and those jobs failed (squashfs input/output error).
"""

import asyncio
from typing import Any, cast

import pytest

from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.dependencies import get_postgres_engine
from compose_api.simulation import handlers
from compose_api.simulation.models import RemoteContainerImage, SimulationRequest
from compose_api.simulation.prebuilt import prebuilt_definition
from compose_api.simulation.simulation_service import SimulationService
from tests.fixtures.mocks import TestBackgroundTask

# one image per test: the database lives for the module, and a recorded download is never fetched again
IMAGE = "ghcr.io/example/simulator@sha256:" + "1" * 64
CONCURRENT_IMAGE = "ghcr.io/example/simulator@sha256:" + "2" * 64


@pytest.mark.asyncio
async def test_a_download_is_found_by_the_simulator_it_was_fetched_for(database_service: DatabaseServiceSQL) -> None:
    simulator_db = database_service.get_simulator_db()
    version = await simulator_db.insert_simulator(prebuilt_definition(IMAGE))

    recorded = await simulator_db.insert_downloaded_simulator(
        RemoteContainerImage.from_container_version(version, source_url=f"docker://{IMAGE}")
    )

    assert recorded.database_id == version.database_id  # no second row for the same definition
    downloaded = await simulator_db.get_downloaded_simulator(simulator_id=version.database_id)
    assert downloaded is not None
    assert downloaded.source_url == f"docker://{IMAGE}"


class _SlowFetchService:
    """Fetches slowly and records the download as the real service does; submits without a cluster."""

    def __init__(self, database_service: DatabaseServiceSQL) -> None:
        self.database_service = database_service
        self.fetches = 0
        self.connections_during_fetch = -1
        self.submitted = 0

    async def download_container(self, remote_container_image: RemoteContainerImage) -> None:
        self.fetches += 1
        await asyncio.sleep(0.5)
        engine = get_postgres_engine()
        assert engine is not None
        self.connections_during_fetch = engine.pool.checkedout()  # type: ignore [attr-defined]
        await self.database_service.get_simulator_db().insert_downloaded_simulator(remote_container_image)

    async def submit_simulation_job(self, **_: Any) -> int:
        self.submitted += 1
        return 900000 + self.submitted


@pytest.mark.asyncio
async def test_concurrent_submissions_fetch_the_container_once(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest
) -> None:
    service = _SlowFetchService(database_service)
    background = TestBackgroundTask()
    background.tasks_to_execute = []  # the mock's list is shared by the class
    request = simulation_request.model_copy(update={"simulator": "sim-a"})
    with override_settings(prebuilt_simulators={"sim-a": CONCURRENT_IMAGE}):
        for _ in range(8):
            await handlers.run_simulation(
                simulation_request=request,
                database_service=database_service,
                simulation_service_slurm=cast(SimulationService, service),
                job_monitor=cast(Any, None),
                background_tasks=background,
            )
        # each submission queues (dispatch, remove its temp dir); run the dispatches together, as the
        # API does when submissions arrive faster than an image is fetched
        dispatches = background.tasks_to_execute[0::2]
        await asyncio.gather(*(dispatch() for dispatch in dispatches))
        for cleanup in background.tasks_to_execute[1::2]:
            cleanup()

    assert service.submitted == 8
    assert service.fetches == 1
    # the seven waiting submissions hold no connection; only the lock's holder does
    assert service.connections_during_fetch == 1
