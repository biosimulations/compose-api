"""Startup brings any database to the current models (compose_api.db.db_utils.create_db).

create_all adds tables but never columns, so the database a deployment already has gets new columns only through a
migration. These pin the three starting points: empty, tracked at an older revision, and never tracked.
"""

import pytest
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.db.db_utils import create_db

NEW_COLUMNS = {
    "hpcrun": {"trace_id", "events_cursor", "last_event_at", "exit_code"},
    "simulation": {"owner_sub", "visibility"},
}


def _column_names(conn: Connection) -> dict[str, set[str]]:
    return {table: {col["name"] for col in inspect(conn).get_columns(table)} for table in NEW_COLUMNS}


async def _columns(engine: AsyncEngine) -> dict[str, set[str]]:
    async with engine.connect() as conn:
        return await conn.run_sync(_column_names)


async def _revision(engine: AsyncEngine) -> str | None:
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()


async def _drop_new_columns(engine: AsyncEngine) -> None:
    """Make the database look like one built before these columns existed."""
    async with engine.begin() as conn:
        for table, columns in NEW_COLUMNS.items():
            for column in columns:
                await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}"))


@pytest.mark.asyncio
async def test_an_empty_database_is_created_at_head(async_postgres_engine: AsyncEngine) -> None:
    # The fixture already ran create_db on this database.
    columns = await _columns(async_postgres_engine)
    assert all(NEW_COLUMNS[t] <= columns[t] for t in NEW_COLUMNS)
    assert await _revision(async_postgres_engine) == "c41f0b7a9d20"


@pytest.mark.asyncio
async def test_a_tracked_database_at_an_older_revision_is_upgraded(async_postgres_engine: AsyncEngine) -> None:
    await _drop_new_columns(async_postgres_engine)
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text("UPDATE alembic_version SET version_num = 'eb3903fb35a7'"))
    await create_db(async_postgres_engine)
    columns = await _columns(async_postgres_engine)
    assert all(NEW_COLUMNS[t] <= columns[t] for t in NEW_COLUMNS)
    assert await _revision(async_postgres_engine) == "c41f0b7a9d20"


@pytest.mark.asyncio
async def test_an_untracked_existing_database_is_upgraded_not_stamped_past_its_columns(
    async_postgres_engine: AsyncEngine,
) -> None:
    await _drop_new_columns(async_postgres_engine)
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text("DROP TABLE alembic_version"))
    await create_db(async_postgres_engine)
    columns = await _columns(async_postgres_engine)
    assert all(NEW_COLUMNS[t] <= columns[t] for t in NEW_COLUMNS)
    assert await _revision(async_postgres_engine) == "c41f0b7a9d20"
