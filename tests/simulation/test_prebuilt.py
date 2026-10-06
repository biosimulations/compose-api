"""Prebuilt simulator images: a request names an owner-published image the deployment lists."""

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pbest.containerization.container_constructor import generate_container_def_file
from pbest.utils.input_types import ContainerizationEngine

from compose_api.common.gateway.utils import allow_list
from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation import handlers
from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import (
    PBAllowList,
    RemoteContainerImage,
    SimulationRequest,
    SimulatorVersion,
)
from compose_api.simulation.prebuilt import (
    UnknownSimulatorError,
    prebuilt_definition,
    prebuilt_image,
    prebuilt_image_of,
)
from compose_api.simulation.simulation_service import SimulationService
from compose_api.simulation.simulator_registry import registry_dependencies
from tests.fixtures.mocks import TestBackgroundTask

IMAGE = "ghcr.io/example/simulator@sha256:" + "0" * 64


def test_definition_is_just_the_image() -> None:
    definition = prebuilt_definition(IMAGE)
    assert definition.representation == f"Bootstrap: docker\nFrom: {IMAGE}\n"
    assert definition.containerization_engine == ContainerizationEngine.APPTAINER
    assert prebuilt_image_of(definition) == IMAGE


def test_the_shared_definition_names_no_prebuilt_image() -> None:
    shared = generate_container_def_file(registry_dependencies(), ContainerizationEngine.APPTAINER)
    assert prebuilt_image_of(shared) is None


def test_only_listed_simulators_resolve() -> None:
    with override_settings(prebuilt_simulators={"sim-a": IMAGE}):
        assert prebuilt_image("sim-a") == IMAGE
        with pytest.raises(UnknownSimulatorError, match="lists: sim-a"):
            prebuilt_image("docker.io/anything:latest")
    with override_settings(prebuilt_simulators={}), pytest.raises(UnknownSimulatorError, match="lists: none"):
        prebuilt_image("sim-a")


@pytest.mark.asyncio
async def test_run_simulation_records_the_prebuilt_simulator(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest
) -> None:
    """The submission's simulator version is the image's definition, distinct from the shared one."""
    request = simulation_request.model_copy(update={"simulator": "sim-a"})
    with override_settings(prebuilt_simulators={"sim-a": IMAGE}):
        experiment = await handlers.run_simulation(
            simulation_request=request,
            database_service=database_service,
            simulation_service_slurm=cast(SimulationService, None),  # used only by the background job
            job_monitor=cast(JobMonitor, None),
            background_tasks=TestBackgroundTask(),  # not run: no cluster needed
            pb_allow_list=PBAllowList(allow_list=allow_list),
        )
    simulator = await database_service.get_simulator_db().get_simulator(simulator_id=experiment.simulator_database_id)
    assert simulator is not None
    assert simulator.container_def.representation == prebuilt_definition(IMAGE).representation
    assert simulator.container_def_hash == get_singularity_hash(prebuilt_definition(IMAGE))


class _RecordingService:
    """Records what would be pulled; the pull succeeds, so nothing is built."""

    def __init__(self) -> None:
        self.pulled: list[RemoteContainerImage] = []

    async def download_container(self, remote_container_image: RemoteContainerImage) -> None:
        self.pulled.append(remote_container_image)


def _version(definition_text: str) -> SimulatorVersion:
    definition = prebuilt_definition(IMAGE).model_copy(update={"representation": definition_text})
    return SimulatorVersion(
        container_def=definition,
        container_def_hash=get_singularity_hash(definition),
        packages=None,
        database_id=1,
        created_at=None,
    )


@pytest.mark.asyncio
async def test_a_prebuilt_simulator_is_pulled_from_its_own_image() -> None:
    service = _RecordingService()
    await handlers._download_or_build_container(
        simulation_service_slurm=cast(Any, service),
        simulator_version=_version(prebuilt_definition(IMAGE).representation),
        hpc_db=cast(Any, None),
        job_monitor=cast(Any, None),
        random_string="abc1234",
    )
    assert [p.source_url for p in service.pulled] == [f"docker://{IMAGE}"]


@pytest.mark.asyncio
async def test_the_shared_simulator_is_still_pulled_by_hash() -> None:
    service = _RecordingService()
    shared = generate_container_def_file(registry_dependencies(), ContainerizationEngine.APPTAINER)
    version = _version(shared.representation)
    with override_settings(simulator_image_repository="ghcr.io/example/registry_env"):
        await handlers._download_or_build_container(
            simulation_service_slurm=cast(Any, service),
            simulator_version=version,
            hpc_db=cast(Any, None),
            job_monitor=cast(Any, None),
            random_string="abc1234",
        )
    assert [p.source_url for p in service.pulled] == [
        f"docker://ghcr.io/example/registry_env:{version.container_def_hash}"
    ]


@pytest.mark.asyncio
async def test_an_unlisted_simulator_is_a_bad_request(
    fastapi_app: FastAPI, local_base_url: str, tmp_path: Path
) -> None:
    omex = tmp_path / "experiment.omex"
    omex.write_bytes(b"not read: the simulator is refused first")
    with override_settings(prebuilt_simulators={"sim-a": IMAGE}):
        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url=local_base_url) as client:
            response = await client.post(
                "/simulation/run",
                params={"simulator": "docker.io/anything:latest"},
                files={"uploaded_file": ("experiment.omex", omex.read_bytes())},
            )
    assert response.status_code == 400
    assert "unknown simulator" in response.json()["detail"]
