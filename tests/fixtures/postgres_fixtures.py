from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
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


@pytest_asyncio.fixture(scope="function")
async def database_service(async_postgres_engine: AsyncEngine) -> AsyncGenerator[DatabaseService]:
    saved_database_service = get_database_service()
    database_service = DatabaseServiceSQL(async_engine=async_postgres_engine)
    set_database_service(database_service)
    yield database_service
    set_database_service(saved_database_service)
