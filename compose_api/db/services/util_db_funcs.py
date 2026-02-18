from sqlalchemy import Result, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from compose_api.db.tables.hpc_tables import ORMHpcRun


async def get_hpcrun_id(
    session: AsyncSession, foreign_key: int | str, column: InstrumentedAttribute[int | str | None]
) -> int | None:
    stmt = select(ORMHpcRun.id).where(column == foreign_key).limit(1)
    result: Result[tuple[int]] = await session.execute(stmt)
    orm_hpcrun_id: int | None = result.scalar_one_or_none()
    return orm_hpcrun_id


async def _get_orm_hpcrun(session: AsyncSession, hpcrun_id: int) -> ORMHpcRun | None:
    stmt1 = select(ORMHpcRun).where(ORMHpcRun.id == hpcrun_id).limit(1)
    result1: Result[tuple[ORMHpcRun]] = await session.execute(stmt1)
    orm_hpc_job: ORMHpcRun | None = result1.scalars().one_or_none()
    return orm_hpc_job
