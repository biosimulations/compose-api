"""Comparisons and their members (compose_api/db/tables/comparison_tables.py)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, override

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from compose_api.db.tables.comparison_tables import ORMComparison, ORMComparisonMember


@dataclass
class ComparisonRow:
    comparison: ORMComparison
    members: list[ORMComparisonMember] = field(default_factory=list)


class ComparisonsDatabaseService(ABC):
    @abstractmethod
    async def insert(self, name: str, source: str, sedml: str, task: str, settings: dict[str, Any]) -> int:
        """A new comparison, `running`, with no members; its id."""

    @abstractmethod
    async def add_member(self, comparison_id: int, simulation_id: int, solver: str) -> None: ...

    @abstractmethod
    async def get(self, comparison_id: int) -> ComparisonRow | None: ...

    @abstractmethod
    async def page(self, limit: int, offset: int, source: str | None = None) -> tuple[list[ComparisonRow], int]:
        """Comparisons, newest first, with their members; and the total."""

    @abstractmethod
    async def set_result(self, comparison_id: int, status: str, result: dict[str, Any] | None) -> None: ...


class ComparisonsORMExecutor(ComparisonsDatabaseService):
    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        self.session_maker = session_maker

    @override
    async def insert(self, name: str, source: str, sedml: str, task: str, settings: dict[str, Any]) -> int:
        async with self.session_maker() as session, session.begin():
            row = ORMComparison(name=name, source=source, sedml=sedml, task=task, settings=settings)
            session.add(row)
            await session.flush()
            return row.id

    @override
    async def add_member(self, comparison_id: int, simulation_id: int, solver: str) -> None:
        async with self.session_maker() as session, session.begin():
            session.add(ORMComparisonMember(comparison_id=comparison_id, simulation_id=simulation_id, solver=solver))

    @override
    async def get(self, comparison_id: int) -> ComparisonRow | None:
        async with self.session_maker() as session:
            comparison = await session.get(ORMComparison, comparison_id)
            if comparison is None:
                return None
            return ComparisonRow(comparison, await _members(session, comparison_id))

    @override
    async def page(self, limit: int, offset: int, source: str | None = None) -> tuple[list[ComparisonRow], int]:
        stmt = select(ORMComparison)
        if source is not None:
            stmt = stmt.where(ORMComparison.source == source)
        async with self.session_maker() as session:
            total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
            found = list(
                (await session.execute(stmt.order_by(ORMComparison.id.desc()).limit(limit).offset(offset))).scalars()
            )
            members: dict[int, list[ORMComparisonMember]] = {c.id: [] for c in found}
            if found:
                rows = await session.execute(
                    select(ORMComparisonMember)
                    .where(ORMComparisonMember.comparison_id.in_(list(members)))
                    .order_by(ORMComparisonMember.id)
                )
                for m in rows.scalars():
                    members[m.comparison_id].append(m)
        return [ComparisonRow(c, members[c.id]) for c in found], int(total)

    @override
    async def set_result(self, comparison_id: int, status: str, result: dict[str, Any] | None) -> None:
        async with self.session_maker() as session, session.begin():
            comparison = await session.get(ORMComparison, comparison_id)
            if comparison is not None:
                comparison.status, comparison.result = status, result


async def _members(session: AsyncSession, comparison_id: int) -> list[ORMComparisonMember]:
    rows = await session.execute(
        select(ORMComparisonMember)
        .where(ORMComparisonMember.comparison_id == comparison_id)
        .order_by(ORMComparisonMember.id)
    )
    return list(rows.scalars())
