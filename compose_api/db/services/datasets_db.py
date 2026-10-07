"""Storage for the datasets a run advertises (docs/plan-observability.md O5)."""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import override

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from compose_api.db.tables.observability_tables import ORMDataset
from compose_api.db.tables.simulator_tables import ORMSimulation
from compose_api.observability.datasets import ArtifactRecord, Dataset, merge
from compose_api.simulation.models import SimulationAccess


@dataclass(frozen=True)
class DatasetQuery:
    simulation_id: int | None = None
    kind: str | None = None
    q: str | None = None  # a substring of the path or display name
    available: bool | None = True  # None: both
    limit: int = 100
    offset: int = 0


class DatasetsDatabaseService(ABC):
    @abstractmethod
    async def register(self, simulation_id: int, hpcrun_id: int | None, records: list[ArtifactRecord]) -> int:
        """Insert or merge each record (``observability.datasets.merge``); the number of rows written."""

    @abstractmethod
    async def get(self, dataset_id: uuid.UUID) -> tuple[Dataset, SimulationAccess] | None:
        """A dataset and its simulation's access record (for the read policy)."""

    @abstractmethod
    async def page(self, query: DatasetQuery, readable: ColumnElement[bool] | None = None) -> tuple[list[Dataset], int]:
        """Datasets matching ``query`` whose simulation satisfies ``readable``, and how many there are in all."""

    @abstractmethod
    async def set_available(self, dataset_id: uuid.UUID, available: bool) -> None:
        pass


class DatasetsORMExecutor(DatasetsDatabaseService):
    def __init__(self, async_session_maker: async_sessionmaker[AsyncSession]):
        self.async_session_maker = async_session_maker

    @override
    async def register(self, simulation_id: int, hpcrun_id: int | None, records: list[ArtifactRecord]) -> int:
        if not records:
            return 0
        async with self.async_session_maker() as session, session.begin():
            paths = list({r.path for r in records})
            result = await session.execute(
                select(ORMDataset)
                .where(ORMDataset.simulation_id == simulation_id, ORMDataset.path.in_(paths))
                .with_for_update()
            )
            rows = {row.path: row for row in result.scalars().all()}
            for record in records:
                row = rows.get(record.path)
                merged = merge(row.to_row() if row is not None else None, record)
                if row is None:
                    row = ORMDataset(simulation_id=simulation_id, path=record.path)
                    session.add(row)
                    rows[record.path] = row
                row.hpcrun_id = hpcrun_id
                row.origin, row.kind, row.media_type = merged.origin, merged.kind, merged.media_type
                row.display_name, row.size_bytes, row.sha256 = merged.display_name, merged.size_bytes, merged.sha256
                row.attributes, row.span_id, row.available = merged.attributes, merged.span_id, merged.available
                await session.flush()
        return len(records)

    @override
    async def get(self, dataset_id: uuid.UUID) -> tuple[Dataset, SimulationAccess] | None:
        stmt = (
            select(ORMDataset, ORMSimulation)
            .join(ORMSimulation, ORMSimulation.id == ORMDataset.simulation_id)
            .where(ORMDataset.id == dataset_id)
        )
        async with self.async_session_maker() as session:
            row = (await session.execute(stmt)).one_or_none()
        if row is None:
            return None
        dataset, simulation = row
        return dataset.to_dataset(), simulation.to_simulation_access()

    @override
    async def page(self, query: DatasetQuery, readable: ColumnElement[bool] | None = None) -> tuple[list[Dataset], int]:
        stmt = select(ORMDataset).join(ORMSimulation, ORMSimulation.id == ORMDataset.simulation_id)
        if readable is not None:
            stmt = stmt.where(readable)
        if query.simulation_id is not None:
            stmt = stmt.where(ORMDataset.simulation_id == query.simulation_id)
        if query.kind is not None:
            stmt = stmt.where(ORMDataset.kind == query.kind)
        if query.available is not None:
            stmt = stmt.where(ORMDataset.available.is_(query.available))
        if query.q:
            pattern = f"%{query.q}%"
            stmt = stmt.where(or_(ORMDataset.path.ilike(pattern), ORMDataset.display_name.ilike(pattern)))
        async with self.async_session_maker() as session:
            total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
            ordered = stmt.order_by(ORMDataset.simulation_id.desc(), ORMDataset.path)
            rows = (await session.execute(ordered.limit(query.limit).offset(query.offset))).scalars().all()
        return [row.to_dataset() for row in rows], int(total)

    @override
    async def set_available(self, dataset_id: uuid.UUID, available: bool) -> None:
        async with self.async_session_maker() as session, session.begin():
            await session.execute(update(ORMDataset).where(ORMDataset.id == dataset_id).values(available=available))
