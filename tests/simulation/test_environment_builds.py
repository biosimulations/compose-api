"""Builds on their own (docs/plan-environment-builds.md, phase 4, E5): an image's status read without starting
anything; a build that has not finished is joined, not started again; and the routes that ask for a build answer an
available image at once, or start the run path's own function in the background."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport
from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

from compose_api.api.routers import registry as registry_router
from compose_api.common.hpc.models import SlurmJob
from compose_api.config import get_settings, override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation import builds, handlers
from compose_api.simulation.builds import ImageState
from compose_api.simulation.models import ImageKind, JobType, SimulatorVersion
from tests.fixtures.postgres_fixtures import shared_definition


@pytest.fixture
def mount(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "mount"
    (root / get_settings().namespace / "images").mkdir(parents=True)
    base = {} if get_settings().simulation_store_base_path else {"simulation_store_base_path": "/store/compose_api"}
    with override_settings(internal_mount_dir=str(root), **base):
        yield root


async def _simulator(database_service: DatabaseServiceSQL) -> SimulatorVersion:
    definition = ContainerizationFileRepr(
        representation=f"Bootstrap: docker\nFrom: busybox\n# {uuid.uuid4().hex}\n",
        containerization_engine=ContainerizationEngine.APPTAINER,
    )
    return await database_service.get_simulator_db().insert_simulator(definition)


def _sif(mount: Path, simulator: SimulatorVersion) -> Path:
    return mount / get_settings().namespace / "images" / f"{simulator.container_def_hash}.sif"


def _job(state: str) -> SlurmJob:
    return SlurmJob(job_id=0, name="b", account="k8s", user_name="k8s", job_state=state)


async def _build_run(database_service: DatabaseServiceSQL, simulator: SimulatorVersion, state: str | None) -> Any:
    hpc_db = database_service.get_hpc_db()
    run = await hpc_db.insert_hpcrun(
        slurmjobid=None, job_type=JobType.BUILD_CONTAINER, ref_id=simulator.database_id,
        correlation_id=f"build-{uuid.uuid4().hex[:8]}", backend="k8s", external_id=f"build-{uuid.uuid4().hex[:6]}",
    )  # fmt: skip
    if state is not None:
        await hpc_db.update_hpcrun_status(hpcrun_id=run.database_id, new_slurm_job=_job(state))
    return run


@pytest.mark.asyncio
async def test_the_status_says_missing_building_failed_or_available(
    database_service: DatabaseServiceSQL, mount: Path
) -> None:
    simulator = await _simulator(database_service)
    assert (await builds.image_status(database_service, simulator)).state == ImageState.MISSING
    await _build_run(database_service, simulator, "FAILED")
    assert (await builds.image_status(database_service, simulator)).state == ImageState.FAILED
    running = await _build_run(database_service, simulator, "RUNNING")
    status = await builds.image_status(database_service, simulator)
    assert status.state == ImageState.BUILDING and status.build is not None
    assert status.build.database_id == running.database_id
    _sif(mount, simulator).write_bytes(b"image")
    status = await builds.image_status(database_service, simulator)
    assert status.state == ImageState.AVAILABLE and status.image is not None and len(status.images) == 1


class _NoDownload:
    async def download_container(self, image: object) -> None:
        raise RuntimeError("not published")


@pytest.mark.asyncio
async def test_a_build_under_way_is_joined_not_started_again(
    database_service: DatabaseServiceSQL, mount: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    simulator = await _simulator(database_service)
    hpc_db = database_service.get_hpc_db()
    running = await _build_run(database_service, simulator, "RUNNING")  # another API process started it

    async def no_second_build(**_: object) -> None:
        raise AssertionError("a second build was started")

    monkeypatch.setattr(handlers, "_build_container_and_wait", no_second_build)
    monkeypatch.setattr(builds, "POLL_SECONDS", 0.05)

    async def the_build_finishes() -> None:
        await asyncio.sleep(0.2)
        _sif(mount, simulator).write_bytes(b"built elsewhere")
        await hpc_db.update_hpcrun_status(hpcrun_id=running.database_id, new_slurm_job=_job("COMPLETED"))

    finishing = asyncio.create_task(the_build_finishes())
    await asyncio.wait_for(
        handlers._download_or_build_container(
            cast(Any, _NoDownload()), simulator, hpc_db, cast(Any, None), "r",
            simulator_db=database_service.get_simulator_db(),
        ),
        timeout=10,
    )  # fmt: skip
    await finishing
    image = await database_service.get_simulator_db().get_available_image(simulator.database_id, ImageKind.SIF)
    assert image is not None and image.hpcrun_id == running.database_id


@pytest_asyncio.fixture
async def client(database_service: DatabaseServiceSQL, mount: Path) -> AsyncGenerator[httpx.AsyncClient]:
    app = FastAPI()
    app.include_router(registry_router.config.router, prefix=registry_router.config.prefix)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_the_build_route_answers_an_available_image_or_starts_the_run_paths_build(
    client: httpx.AsyncClient, database_service: DatabaseServiceSQL, mount: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    simulator = await _simulator(database_service)
    started: list[int] = []

    async def ensure_image(simulator_version: SimulatorVersion, **_: object) -> None:
        started.append(simulator_version.database_id)
        _sif(mount, simulator_version).write_bytes(b"built")

    monkeypatch.setattr(handlers, "ensure_image", ensure_image)
    for name in ("get_required_simulation_service", "get_required_job_monitor"):
        monkeypatch.setattr(registry_router, name, lambda: None)

    status = await client.get(f"/registry/simulators/{simulator.database_id}/images")
    assert status.status_code == 200 and status.json()["state"] == "missing"

    first = await client.post(f"/registry/simulators/{simulator.database_id}/build")
    assert first.status_code == 202 and first.json()["state"] == "building"
    assert started == [simulator.database_id]  # the background task ran once the response was sent

    again = await client.post(f"/registry/simulators/{simulator.database_id}/build")
    assert again.status_code == 200 and again.json()["state"] == "available"
    assert started == [simulator.database_id]  # nothing started for an available image

    assert (await client.get("/registry/simulators/999999999/images")).status_code == 404
    assert (await client.post("/registry/environments/no-such-env/build")).status_code == 404


@pytest.mark.asyncio
async def test_an_environments_images_are_those_of_its_current_definition(
    client: httpx.AsyncClient, database_service: DatabaseServiceSQL
) -> None:
    response = await client.get("/registry/environments/registry_env/images")
    assert response.status_code == 200
    body = response.json()
    expected = shared_definition()  # registry_env's default here (tests/fixtures/postgres_fixtures.py)
    simulator = await database_service.get_simulator_db().get_simulator(body["simulator_id"])
    assert simulator is not None and simulator.container_def.representation == expected.representation
    assert body["environment"] == "registry_env"
