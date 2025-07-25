from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer  # type: ignore [import-untyped]

from compose_api.dependencies import (
    get_database_service,
    get_postgres_engine,
    set_database_service,
    set_postgres_engine,
)
from compose_api.simulation.database_service import DatabaseService, DatabaseServiceSQL
from compose_api.simulation.tables_orm import create_db


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    with PostgresContainer("postgres:15") as postgres:
        url = postgres.get_connection_url().replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        yield url


@pytest_asyncio.fixture(scope="function")
async def async_postgres_engine(postgres_url: str) -> AsyncGenerator[AsyncEngine, None]:
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
async def database_service(async_postgres_engine: AsyncEngine) -> AsyncGenerator[DatabaseService, None]:
    saved_database_service = get_database_service()
    database_service = DatabaseServiceSQL(async_engine=async_postgres_engine)
    set_database_service(database_service)
    yield database_service
    set_database_service(saved_database_service)
