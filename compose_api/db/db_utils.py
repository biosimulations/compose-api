import pathlib

from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncEngine
from sqlalchemy.orm import DeclarativeBase

_ALEMBIC_INI = pathlib.Path(__file__).parent.parent.parent / "alembic.ini"


class DeclarativeTableBase(AsyncAttrs, DeclarativeBase):
    pass


def _do_upgrade(sync_conn: Connection) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(_ALEMBIC_INI))
    cfg.attributes["connection"] = sync_conn
    command.upgrade(cfg, "head")


# The last revision before the database was migrated at startup. A database that predates alembic tracking was built
# by create_all from the models of that time, so it is at least this revision; later revisions are idempotent.
_UNTRACKED_BASELINE = "eb3903fb35a7"


def _stamp_untracked(sync_conn: Connection, was_empty: bool) -> None:
    """Give a database alembic does not track yet a revision to upgrade from.

    An empty database was just built by create_all from the current models: stamp it at head. One that already had
    tables was built earlier: stamp it at the baseline, so the upgrade that follows applies everything after it.
    """
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    cfg = Config(str(_ALEMBIC_INI))
    script = ScriptDirectory.from_config(cfg)

    head = script.get_current_head()
    if head is None:
        return  # No migrations exist yet, nothing to stamp to

    ctx = MigrationContext.configure(sync_conn)
    if ctx.get_current_revision() is not None:
        return  # DB already tracked by alembic, leave it alone

    ctx.stamp(script, head if was_empty else _UNTRACKED_BASELINE)


async def upgrade_db(connection_engine: AsyncEngine) -> None:
    async with connection_engine.begin() as conn:
        await conn.run_sync(_do_upgrade)


async def create_db(async_engine: AsyncEngine) -> None:
    """Bring the database to the current models: create missing tables, then apply pending migrations.

    create_all adds tables but never columns, so a column added to an existing table arrives only through a migration.
    """
    async with async_engine.begin() as conn:
        was_empty = not await conn.run_sync(lambda c: inspect(c).has_table("simulation"))
        await conn.run_sync(DeclarativeTableBase.metadata.create_all)
        await conn.run_sync(_stamp_untracked, was_empty)
    await upgrade_db(async_engine)


package_table_name = "packages"
