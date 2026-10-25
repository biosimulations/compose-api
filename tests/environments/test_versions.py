"""Environment versions, step 2 (docs/plan-environment-versions.md): the deployment's own definition is an
environment's default version, created the first time it is seen, and every run records the version it used."""

import asyncio
import uuid
from typing import cast

import pytest
from pbest.containerization.container_constructor import generate_container_def_file
from pbest.utils.input_types import ContainerizationEngine

from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.db.tables.simulator_tables import ORMSimulation
from compose_api.environments.versions import version_for
from compose_api.simulation import handlers
from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import SimulationRequest, VersionState
from compose_api.simulation.prebuilt import UnknownSimulatorError, prebuilt_definition
from compose_api.simulation.simulation_service import SimulationService
from compose_api.simulation.simulator_registry import registry_dependencies, registry_libraries
from tests.fixtures.mocks import TestBackgroundTask


def _image(tag: str) -> str:
    return f"ghcr.io/example/simulator@sha256:{tag * 64}"


def _name() -> str:
    """The test database lives for the module: each test's prebuilt simulator gets a name of its own."""
    return f"sim-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_the_shared_environment_runs_its_deployed_definition_as_its_default_version(
    database_service: DatabaseServiceSQL,
) -> None:
    version, simulator = await version_for(database_service, None)
    expected = generate_container_def_file(registry_dependencies(), ContainerizationEngine.APPTAINER)
    assert simulator.container_def_hash == get_singularity_hash(expected)  # the same image as before versions
    assert (version.environment, version.state, version.origin) == ("registry_env", VersionState.READY, "registry")
    assert version.simulator_id == simulator.database_id
    assert version.spec == {"libraries": registry_libraries()}
    assert version.label == f"registry_env@{version.number}"
    assert await database_service.get_environments_db().get_default("registry_env") == version
    again, _ = await version_for(database_service, None)
    assert again == version


@pytest.mark.asyncio
async def test_a_new_pin_is_a_new_version_and_a_rollback_returns_to_the_old_one(
    database_service: DatabaseServiceSQL,
) -> None:
    name, environments_db = _name(), database_service.get_environments_db()
    with override_settings(prebuilt_simulators={name: _image("a")}):
        first, simulator = await version_for(database_service, name)
    assert (first.number, first.image, first.spec) == (1, _image("a"), None)
    assert simulator.container_def.representation == prebuilt_definition(_image("a")).representation

    with override_settings(prebuilt_simulators={name: _image("b")}):
        second, _ = await version_for(database_service, name)
    assert (second.number, second.image) == (2, _image("b"))
    assert await environments_db.get_default(name) == second

    with override_settings(prebuilt_simulators={name: _image("a")}):
        rolled_back, _ = await version_for(database_service, name)
    assert rolled_back == first
    assert await environments_db.get_default(name) == first
    assert [v.number for v in await environments_db.list_versions(name)] == [2, 1]


@pytest.mark.asyncio
async def test_a_name_the_deployment_does_not_list_has_no_version(database_service: DatabaseServiceSQL) -> None:
    name = _name()
    with override_settings(prebuilt_simulators={}), pytest.raises(UnknownSimulatorError):
        await version_for(database_service, name)
    assert await database_service.get_environments_db().list_versions(name) == []


@pytest.mark.asyncio
async def test_concurrent_adoptions_of_one_definition_make_one_version(database_service: DatabaseServiceSQL) -> None:
    name = _name()
    with override_settings(prebuilt_simulators={name: _image("c")}):
        _, simulator = await version_for(database_service, name)
    other = _name()
    environments_db = database_service.get_environments_db()
    adopted = await asyncio.gather(*(
        environments_db.adopt_deployed(other, "prebuilt", simulator.database_id, image=_image("c")) for _ in range(5)
    ))  # fmt: skip
    assert len({v.database_id for v in adopted}) == 1
    assert [v.number for v in await environments_db.list_versions(other)] == [1]


@pytest.mark.asyncio
async def test_a_run_records_its_environment_version(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest
) -> None:
    name = _name()
    with override_settings(prebuilt_simulators={name: _image("d")}):
        experiment = await handlers.run_simulation(
            simulation_request=simulation_request.model_copy(update={"simulator": name}),
            database_service=database_service,
            simulation_service_slurm=cast(SimulationService, None),  # used only by the submission worker
            job_monitor=cast(JobMonitor, None),
            background_tasks=TestBackgroundTask(),
        )
    version = await database_service.get_environments_db().get_default(name)
    assert version is not None and version.simulator_id == experiment.simulator_database_id
    async with database_service.async_sessionmaker() as session:
        simulation = await session.get(ORMSimulation, experiment.simulation_database_id)
    assert simulation is not None and simulation.environment_version_id == version.database_id
