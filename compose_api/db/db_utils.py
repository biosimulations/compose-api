import pathlib

from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncEngine
from sqlalchemy.orm import DeclarativeBase

_ALEMBIC_INI = pathlib.Path(__file__).parent.parent.parent / "alembic.ini"


class DeclarativeTableBase(AsyncAttrs, DeclarativeBase):
    pass


def _do_upgrade(sync_conn: Connection) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.attributes["connection"] = sync_conn
    command.upgrade(cfg, "head")


def _stamp_head(sync_conn: Connection) -> None:
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

    ctx.stamp(script, head)


async def upgrade_db(connection_engine: AsyncEngine) -> None:
    async with connection_engine.connect() as conn:
        await conn.run_sync(_do_upgrade)


async def create_db(async_engine: AsyncEngine) -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(DeclarativeTableBase.metadata.create_all)
        await conn.run_sync(_stamp_head)


package_table_name = "packages"
