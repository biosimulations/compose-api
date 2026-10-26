"""Environment versions, step 2 (docs/plan-environment-versions.md): the deployment's own definition is an
environment's default version, created the first time it is seen, and every run records the version it used."""

import asyncio
import uuid
from typing import cast

import pytest

from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.db.tables.simulator_tables import ORMSimulation
from compose_api.environments.versions import NoDefaultVersionError, version_for
from compose_api.simulation import handlers
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import SimulationRequest
from compose_api.simulation.prebuilt import prebuilt_definition
from compose_api.simulation.simulation_service import SimulationService
from tests.fixtures.mocks import TestBackgroundTask
from tests.fixtures.postgres_fixtures import register_prebuilt, unregister_prebuilt


def _image(tag: str) -> str:
    return f"ghcr.io/example/simulator@sha256:{tag * 64}"


PREBUILT = "viva-pde-particle"  # the prebuilt environment environments.yaml declares


def _name() -> str:
    """The test database lives for the module: each test's prebuilt simulator gets a name of its own."""
    return f"sim-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_the_shared_environment_runs_its_default_and_without_one_refuses(
    database_service: DatabaseServiceSQL,
) -> None:
    """D8.1: a version is a database record. The shared environment's default (here the one the test database seeds)
    is what a run that names none takes; with no default (a fresh deployment) the run is refused with what to do,
    rather than adopting a definition the service generates."""
    from sqlalchemy import select, update

    from compose_api.db.tables.environment_tables import ORMEnvironment
    from compose_api.environments.versions import NoDefaultVersionError

    environments_db = database_service.get_environments_db()
    default = await environments_db.get_default("registry_env")
    assert default is not None
    version, simulator = await version_for(database_service, None)
    assert version == default and simulator.database_id == default.simulator_id
    async with database_service.async_sessionmaker() as session, session.begin():
        kept = (
            await session.execute(
                select(ORMEnvironment.default_version_id).where(ORMEnvironment.name == "registry_env")
            )
        ).scalar_one()
        await session.execute(
            update(ORMEnvironment).where(ORMEnvironment.name == "registry_env").values(default_version_id=None)
        )
    try:
        with pytest.raises(NoDefaultVersionError, match="environments create registry_env"):
            await version_for(database_service, None)
    finally:
        async with database_service.async_sessionmaker() as session, session.begin():
            query = update(ORMEnvironment).where(ORMEnvironment.name == "registry_env")
            await session.execute(query.values(default_version_id=kept))


@pytest.mark.asyncio
async def test_a_prebuilt_run_takes_its_default_and_earlier_versions_stay_by_number(
    database_service: DatabaseServiceSQL,
) -> None:
    """D8.3: a prebuilt image is a version an administrator registers; runs take the default, and an earlier image
    stays runnable by its number (D8.2)."""
    first = await register_prebuilt(database_service, PREBUILT, _image("a"))
    taken, simulator = await version_for(database_service, PREBUILT)
    assert taken.database_id == first.database_id and taken.image == _image("a")
    assert simulator.container_def.representation == prebuilt_definition(_image("a")).representation
    second = await register_prebuilt(database_service, PREBUILT, _image("b"))
    assert (await version_for(database_service, PREBUILT))[0].database_id == second.database_id
    by_number, _ = await version_for(database_service, PREBUILT, first.number)
    assert by_number.database_id == first.database_id


@pytest.mark.asyncio
async def test_a_prebuilt_environment_with_no_version_says_how_to_register_one(
    database_service: DatabaseServiceSQL,
) -> None:
    await unregister_prebuilt(database_service, PREBUILT)
    with pytest.raises(NoDefaultVersionError, match=f"environments create {PREBUILT} --image"):
        await version_for(database_service, PREBUILT)


@pytest.mark.asyncio
async def test_concurrent_adoptions_of_one_definition_make_one_version(database_service: DatabaseServiceSQL) -> None:
    from compose_api.simulation.builds import simulator_for

    simulator = await simulator_for(database_service.get_simulator_db(), prebuilt_definition(_image("c")))
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
    await register_prebuilt(database_service, PREBUILT, _image("d"))
    experiment = await handlers.run_simulation(
        simulation_request=simulation_request.model_copy(update={"simulator": PREBUILT}),
        database_service=database_service,
        simulation_service_slurm=cast(SimulationService, None),  # used only by the submission worker
        job_monitor=cast(JobMonitor, None),
        background_tasks=TestBackgroundTask(),
    )
    version = await database_service.get_environments_db().get_default(PREBUILT)
    assert version is not None and version.simulator_id == experiment.simulator_database_id
    async with database_service.async_sessionmaker() as session:
        simulation = await session.get(ORMSimulation, experiment.simulation_database_id)
    assert simulation is not None and simulation.environment_version_id == version.database_id


@pytest.mark.asyncio
async def test_a_run_with_no_default_to_take_is_unavailable_not_an_error() -> None:
    """Whichever route started it, the app answers 503 with what an administrator does (D8.1)."""
    from compose_api.api import main
    from compose_api.environments.versions import NoDefaultVersionError

    assert main.app.exception_handlers[NoDefaultVersionError] is main._no_default_version
    response = await main._no_default_version(None, NoDefaultVersionError("registry_env has no version yet"))  # type: ignore[arg-type]
    assert response.status_code == 503 and b"registry_env has no version yet" in response.body
