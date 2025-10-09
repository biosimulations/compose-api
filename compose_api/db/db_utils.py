from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncEngine
from sqlalchemy.orm import DeclarativeBase


class DeclarativeTableBase(AsyncAttrs, DeclarativeBase):
    pass


async def create_db(async_engine: AsyncEngine) -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(DeclarativeTableBase.metadata.create_all)


package_table_name = "packages"
