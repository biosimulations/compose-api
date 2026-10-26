import json
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
import pytest_asyncio
from pbest.utils.input_types import ContainerizationFileRepr
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer  # type: ignore [import-untyped]

from compose_api.db.database_service import DatabaseService, DatabaseServiceSQL
from compose_api.db.db_utils import create_db
from compose_api.dependencies import (
    get_database_service,
    get_postgres_engine,
    set_database_service,
    set_postgres_engine,
)
from compose_api.simulation.models import EnvironmentVersion


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str]:
    with PostgresContainer("postgres:15", username="test", password="test", dbname="test") as postgres:  # noqa: S106 Possible hardcoded password assigned to argument: "password"
        url = postgres.get_connection_url().replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        yield url


@pytest_asyncio.fixture(scope="function")
async def async_postgres_engine(postgres_url: str) -> AsyncGenerator[AsyncEngine]:
    engine = create_async_engine(postgres_url, echo=True)
    prev_engine: AsyncEngine | None = get_postgres_engine()
    try:
        set_postgres_engine(engine)
        await create_db(engine)
        yield engine
    finally:
        set_postgres_engine(prev_engine)
        await engine.dispose()


def shared_definition() -> ContainerizationFileRepr:
    """The definition registry_env's test default runs: pbest's, as the service generated it before versions were
    database records (docs/plan-environment-composition.md, D8.1). The SLURM tests build and run it."""
    from pbest.containerization.container_constructor import generate_container_def_file
    from pbest.utils.input_types import ContainerizationEngine

    from compose_api.simulation.simulator_registry import registry_dependencies

    return generate_container_def_file(registry_dependencies(), ContainerizationEngine.APPTAINER)


async def seed_shared_default(database_service: DatabaseService) -> None:
    """registry_env with a ready default, as every deployment has once an administrator made one: runs that name no
    version take it. Kept when a test made its own default."""
    from compose_api.simulation.builds import simulator_for

    simulator = await simulator_for(database_service.get_simulator_db(), shared_definition())
    environments_db = database_service.get_environments_db()
    version = await environments_db.adopt_deployed("registry_env", "shared", simulator.database_id, origin="registry")
    # what it provides, as read back from registry_env@5's image on 2026-10-26: the manifest SED-ML runs are
    # translated against and the checker reads (D8.4)
    detail = await environments_db.get_by_number("registry_env", version.number)
    if detail is not None and detail.interfaces is None:
        interfaces = json.loads((Path(__file__).parent / "resources" / "registry_env.interfaces.json").read_text())
        await environments_db.set_contents(version.database_id, None, interfaces)


@pytest_asyncio.fixture(scope="function")
async def database_service(async_postgres_engine: AsyncEngine) -> AsyncGenerator[DatabaseService]:
    saved_database_service = get_database_service()
    database_service = DatabaseServiceSQL(async_engine=async_postgres_engine)
    await seed_shared_default(database_service)
    set_database_service(database_service)
    yield database_service
    set_database_service(saved_database_service)


async def register_prebuilt(database_service: DatabaseService, name: str, image: str) -> EnvironmentVersion:
    """A prebuilt environment's image, registered as a ready version and made its default, as an administrator does
    with `environments create <name> --image …` and `environments default` (docs/plan-environment-composition.md,
    D8.3). ``name`` must be one environments.yaml declares as prebuilt."""
    from compose_api.db.services.environments_db import VersionSource
    from compose_api.simulation.builds import simulator_for
    from compose_api.simulation.models import VersionState
    from compose_api.simulation.prebuilt import prebuilt_definition

    simulator = await simulator_for(database_service.get_simulator_db(), prebuilt_definition(image))
    environments_db = database_service.get_environments_db()
    version, _ = await environments_db.create_version(
        name, "prebuilt", simulator.database_id, VersionSource(image=image)
    )
    await environments_db.set_state(version.database_id, VersionState.READY)
    await environments_db.set_default(name, version.database_id)
    return version.model_copy(update={"state": VersionState.READY})


async def unregister_prebuilt(database_service: DatabaseService, name: str) -> None:
    """The prebuilt environment with no default, so not offered here (a deployment that has registered none)."""
    from sqlalchemy import update

    from compose_api.db.tables.environment_tables import ORMEnvironment

    async with database_service.async_sessionmaker() as session, session.begin():  # type: ignore[attr-defined]
        await session.execute(update(ORMEnvironment).where(ORMEnvironment.name == name).values(default_version_id=None))
