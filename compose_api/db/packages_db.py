import logging
from abc import ABC, abstractmethod

from sqlalchemy import Result, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from compose_api.btools.bsander.bsandr_utils.input_types import ExperimentPrimaryDependencies
from compose_api.db.tables_orm import (
    BiGraphEdgeTypeDB,
    ORMBiGraphEdge,
    ORMPackage,
    ORMPackageToEdge,
    ORMSimulatorToPackage,
    PackageTypeDB,
)
from compose_api.simulation.models import (
    BiGraphEdge,
    BiGraphEdgeType,
    BiGraphPackage,
    BiGraphProcess,
    BiGraphStep,
    PackageOutline,
)

logger = logging.getLogger(__name__)


class PackageDB(ABC):
    @abstractmethod
    async def insert_package(self, package_outline: PackageOutline) -> BiGraphPackage:
        pass

    @abstractmethod
    async def list_simulator_packages(self, simulator_id: int) -> list[BiGraphPackage]:
        pass

    @abstractmethod
    async def list_all_edges_in_package(self, package_id: int) -> tuple[list[BiGraphProcess], list[BiGraphStep]]:
        pass

    @abstractmethod
    async def list_edges_in_package(
        self, package_id: int, edge_type: BiGraphEdgeType
    ) -> list[BiGraphProcess] | list[BiGraphStep]:
        pass

    @abstractmethod
    async def delete_bigraph_package(self, package_id: BiGraphPackage) -> None:
        pass

    @abstractmethod
    async def delete_bigraph_edge(self, compute: BiGraphEdge) -> None:
        pass

    @abstractmethod
    async def dependencies_not_in_database(
        self, dependencies: ExperimentPrimaryDependencies
    ) -> ExperimentPrimaryDependencies:
        pass

    @abstractmethod
    async def list_packages_from_dependencies(
        self, dependencies: ExperimentPrimaryDependencies
    ) -> list[BiGraphPackage]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class PackageDBSQL(PackageDB):
    async_session_maker: async_sessionmaker[AsyncSession]

    def __init__(self, async_engine_session_maker: async_sessionmaker[AsyncSession]) -> None:
        self.async_session_maker = async_engine_session_maker

    @staticmethod
    async def _insert_edge(session: AsyncSession, edge: BiGraphEdge) -> ORMBiGraphEdge:
        new_orm_process = ORMBiGraphEdge(
            module=edge.module,
            name=edge.name,
            edge_type=BiGraphEdgeTypeDB.from_edge_type(edge.edge_type),
            input=edge.inputs,
            output=edge.outputs,
        )
        session.add(new_orm_process)
        return new_orm_process

    @override
    async def insert_package(self, package: PackageOutline) -> BiGraphPackage:
        async with self.async_session_maker() as session:
            new_orm_package = ORMPackage(
                source_uri=package.source_uri.geturl(),
                package_type=PackageTypeDB.from_package_type(package.package_type),
                name=package.name,
            )
            session.add(new_orm_package)
            orm_processes: list[ORMBiGraphEdge] = []
            for process in package.processes:
                orm_processes.append(await self._insert_edge(session, process))
            for step in package.steps:
                orm_processes.append(await self._insert_edge(session, step))
            await session.flush()

            for orm_process in orm_processes:
                relationship = ORMPackageToEdge(package_id=new_orm_package.id, edge_id=orm_process.id)
                session.add(relationship)
            return new_orm_package.to_bigraph_package(package.processes, package.steps)

    async def list_simulator_packages(self, simulator_id: int) -> list[BiGraphPackage]:
        async with self.async_session_maker() as session:
            stmt = (
                select(ORMPackage)
                .join(ORMSimulatorToPackage, onclause=ORMSimulatorToPackage.package_id == ORMPackage.id)
                .where(ORMSimulatorToPackage.simulator_id == simulator_id)
            )

            result: Result[tuple[ORMPackage]] = await session.execute(stmt)
            orm_packages = result.scalars().all()
            packages: list[BiGraphPackage] = []
            for row in orm_packages:
                processes, steps = await self._list_edges_in_package(row.id)
                packages.append(row.to_bigraph_package(processes=processes, steps=steps))

            return packages

    async def list_all_edges_in_package(self, package_id: int) -> tuple[list[BiGraphProcess], list[BiGraphStep]]:
        return await self._list_edges_in_package(package_id=package_id)

    async def list_edges_in_package(
        self, package_id: int, edge_type: BiGraphEdgeType
    ) -> list[BiGraphProcess] | list[BiGraphStep]:
        match edge_type:
            case BiGraphEdgeType.PROCESS:
                return (await self._list_edges_in_package(package_id))[0]
            case BiGraphEdgeType.STEP:
                return (await self._list_edges_in_package(package_id))[1]
        raise ValueError(f"Edge type {edge_type} not supported")

    async def _list_edges_in_package(self, package_id: int) -> tuple[list[BiGraphProcess], list[BiGraphStep]]:
        async with self.async_session_maker() as session:
            stmt = (
                select(ORMBiGraphEdge)
                .join(ORMPackageToEdge, onclause=ORMPackageToEdge.edge_id == ORMBiGraphEdge.id)
                .where(ORMPackageToEdge.package_id == package_id)
            )

            result: Result[tuple[ORMBiGraphEdge]] = await session.execute(stmt)
            orm_edges = result.scalars().all()

            processes = []
            steps = []
            for edge in orm_edges:
                if edge.edge_type == BiGraphEdgeTypeDB.PROCESS:
                    processes.append(edge.to_bigraph_process())
                elif edge.edge_type == BiGraphEdgeTypeDB.STEP:
                    steps.append(edge.to_bigraph_step())

            return processes, steps

    async def delete_bigraph_package(self, package: BiGraphPackage) -> None:
        async with self.async_session_maker() as session:
            await session.delete(ORMPackage.from_bigraph_package(package))

    async def delete_bigraph_edge(self, compute: BiGraphEdge) -> None:
        async with self.async_session_maker() as session:
            await session.delete(ORMBiGraphEdge.from_bigraph_edge(compute))

    async def dependencies_not_in_database(
        self, dependencies: ExperimentPrimaryDependencies
    ) -> ExperimentPrimaryDependencies:
        async with self.async_session_maker() as session:
            stmt = select(ORMPackage).where(ORMPackage.name.in_(dependencies.pypi_dependencies))
            result: Result[tuple[ORMPackage]] = await session.execute(stmt)
            orm_packages = result.scalars().all()
            names: tuple[str, ...] = tuple(package.name for package in orm_packages)
            pypi_not_in_database: list[str] = []
            for pypi in dependencies.pypi_dependencies:
                if pypi not in names:
                    pypi_not_in_database.append(pypi)
            conda_not_in_database: list[str] = []
            for conda in dependencies.conda_dependencies:
                if conda not in names:
                    conda_not_in_database.append(conda)
            return ExperimentPrimaryDependencies(
                pypi_dependencies=pypi_not_in_database, conda_dependencies=conda_not_in_database
            )

    async def list_packages_from_dependencies(
        self, dependencies: ExperimentPrimaryDependencies
    ) -> list[BiGraphPackage]:
        async with self.async_session_maker() as session:
            stmt = select(ORMPackage).where(ORMPackage.name.in_(dependencies.pypi_dependencies))
            result: Result[tuple[ORMPackage]] = await session.execute(stmt)
            orm_packages = result.scalars().all()
            packages: list[BiGraphPackage] = []
            for row in orm_packages:
                processes, steps = await self._list_edges_in_package(package_id=row.id)
                packages.append(row.to_bigraph_package(processes=processes, steps=steps))
            return packages

    @override
    async def close(self) -> None:
        pass
