"""Startup brings any database to the current models (compose_api.db.db_utils.create_db).

create_all adds tables but never columns or enum labels, so the database a deployment already has gets them only through
a migration. These pin the three starting points: empty, tracked at an older revision, and never tracked.
"""

import pytest
from sqlalchemy import Connection, Enum, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.db.db_utils import DeclarativeTableBase, create_db
from compose_api.simulation.models import JobType, SimulationRequest, SimulatorVersion

HEAD = "7c3a9e1d5b20"

NEW_COLUMNS = {
    "hpcrun": {"trace_id", "events_cursor", "last_event_at", "exit_code", "backend", "external_id"},
    "simulation": {
        "owner_sub",
        "visibility",
        "dispatch_heartbeat_at",
        "labels",
        "tags",
        "description",
        "environment_version_id",
    },
    "comparison": {"collection", "suite_run"},
    "suite_run": {"sources", "next_source", "lease_owner", "lease_expires_at"},
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
    assert await _revision(async_postgres_engine) == HEAD


@pytest.mark.asyncio
async def test_a_tracked_database_at_an_older_revision_is_upgraded(async_postgres_engine: AsyncEngine) -> None:
    await _drop_new_columns(async_postgres_engine)
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text("UPDATE alembic_version SET version_num = 'eb3903fb35a7'"))
    await create_db(async_postgres_engine)
    columns = await _columns(async_postgres_engine)
    assert all(NEW_COLUMNS[t] <= columns[t] for t in NEW_COLUMNS)
    assert await _revision(async_postgres_engine) == HEAD


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
    assert await _revision(async_postgres_engine) == HEAD


async def _enum_labels(engine: AsyncEngine) -> dict[str, set[str]]:
    query = text("SELECT t.typname, e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid")
    async with engine.connect() as conn:
        labels: dict[str, set[str]] = {}
        for name, label in (await conn.execute(query)).tuples():
            labels.setdefault(name, set()).add(label)
        return labels


@pytest.mark.asyncio
async def test_every_model_enum_label_exists_in_the_database(async_postgres_engine: AsyncEngine) -> None:
    """The drift alarm: a member added to a model enum needs a revision that adds its label (``ALTER TYPE``)."""
    labels = await _enum_labels(async_postgres_engine)
    for table in DeclarativeTableBase.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, Enum) and column.type.name:
                assert set(column.type.enums) <= labels[column.type.name], (table.name, column.name)


@pytest.mark.asyncio
async def test_a_job_status_type_built_before_pending_gains_it(async_postgres_engine: AsyncEngine) -> None:
    # Production's jobstatusdb was built by create_all before JobStatusDB.PENDING existed.
    labels = sorted((await _enum_labels(async_postgres_engine))["jobstatusdb"] - {"PENDING"})
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text("ALTER TYPE jobstatusdb RENAME TO jobstatusdb_current"))
        await conn.execute(text(f"CREATE TYPE jobstatusdb AS ENUM ({', '.join(repr(label) for label in labels)})"))
        await conn.execute(
            text("ALTER TABLE hpcrun ALTER COLUMN status TYPE jobstatusdb USING status::text::jobstatusdb")
        )
        await conn.execute(text("DROP TYPE jobstatusdb_current"))
        await conn.execute(text("UPDATE alembic_version SET version_num = 'c41f0b7a9d20'"))
    await create_db(async_postgres_engine)
    assert "PENDING" in (await _enum_labels(async_postgres_engine))["jobstatusdb"]
    assert await _revision(async_postgres_engine) == HEAD


@pytest.mark.asyncio
async def test_existing_simulations_get_a_submission_row_for_their_state(
    async_postgres_engine: AsyncEngine,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    """Simulations from before the queue: one that reached SLURM is `submitted`; one that never did is `failed`, so the
    worker never takes up a run whose files were never staged."""
    simulator_db = database_service.get_simulator_db()
    ran = (await simulator_db.insert_simulation(simulation_request, "backfill-ran", simulator)).database_id
    never = (await simulator_db.insert_simulation(simulation_request, "backfill-never", simulator)).database_id
    await database_service.get_hpc_db().insert_hpcrun(4242, JobType.SIMULATION, ran, "backfill-corr")
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text("DELETE FROM submission"))
        await conn.execute(text("UPDATE alembic_version SET version_num = '9e4b2f6a1c05'"))
    await create_db(async_postgres_engine)
    query = text(f"SELECT simulation_id, state FROM submission WHERE simulation_id IN ({ran}, {never})")  # noqa: S608
    async with async_postgres_engine.connect() as conn:
        states = {row[0]: row[1] for row in (await conn.execute(query)).all()}
    assert states == {ran: "submitted", never: "failed"}
    assert await _revision(async_postgres_engine) == HEAD
