"""The deployment's identity on `GET /health` (#543): stable for one database, different between databases, optional."""

import asyncio
from collections.abc import Generator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from compose_api.api.main import app
from compose_api.db.deployment import ensure_deployment_id
from compose_api.dependencies import get_deployment_id, set_deployment_id


@pytest.fixture
def restore_deployment_id() -> Generator[None]:
    previous = get_deployment_id()
    yield
    set_deployment_id(previous)


@pytest.mark.asyncio
async def test_the_id_survives_a_restart(async_postgres_engine: AsyncEngine) -> None:
    first = await ensure_deployment_id(async_postgres_engine)
    assert first == await ensure_deployment_id(async_postgres_engine)

    # A restart is a new process with a new engine on the same database.
    restarted = create_async_engine(async_postgres_engine.url)
    try:
        assert await ensure_deployment_id(restarted) == first
    finally:
        await restarted.dispose()


@pytest.mark.asyncio
async def test_replicas_starting_together_agree(async_postgres_engine: AsyncEngine) -> None:
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text("DELETE FROM deployment"))
    ids = await asyncio.gather(*(ensure_deployment_id(async_postgres_engine) for _ in range(8)))
    assert len(set(ids)) == 1


@pytest.mark.asyncio
async def test_another_database_gets_another_id(async_postgres_engine: AsyncEngine) -> None:
    first = await ensure_deployment_id(async_postgres_engine)
    # A database without the row stands in for another deployment's.
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text("DELETE FROM deployment"))
    assert await ensure_deployment_id(async_postgres_engine) != first


@pytest.mark.asyncio
@pytest.mark.usefixtures("restore_deployment_id")
async def test_health_reports_the_id() -> None:
    set_deployment_id("c0mp-test-1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        health = (await client.get("/health")).json()
    assert health["deployment_id"] == "c0mp-test-1"
    assert {"docs", "version"} <= health.keys()


@pytest.mark.asyncio
@pytest.mark.usefixtures("restore_deployment_id")
async def test_health_leaves_the_id_out_until_it_is_known() -> None:
    set_deployment_id(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        health = (await client.get("/health")).json()
    assert "deployment_id" not in health
