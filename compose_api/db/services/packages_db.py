import logging
from abc import ABC, abstractmethod
from typing import Any

from pbest.utils.input_types import ExperimentPrimaryDependencies
from sqlalchemy import Result, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from compose_api.db.tables.package_tables import (
    BiGraphComputeTypeDB,
    ORMBiGraphCompute,
    ORMPackage,
    PackageTypeDB,
)
from compose_api.db.tables.simulator_tables import (
    ORMSimulatorToPackage,
)
from compose_api.simulation.models import (
    BiGraphCompute,
    BiGraphComputeOutline,
    BiGraphComputeType,
    BiGraphProcess,
    BiGraphStep,
    PackageOutline,
    RegisteredPackage,
)

logger = logging.getLogger(__name__)


class PackageDatabaseService(ABC):
    @abstractmethod
    async def insert_package(self, package_outline: PackageOutline) -> RegisteredPackage:
        pass

    @abstractmethod
    async def list_simulator_packages(self, simulator_id: int) -> list[RegisteredPackage]:
        pass

    @abstractmethod
    async def list_all_computes_in_package(self, package_id: int) -> tuple[list[BiGraphProcess], list[BiGraphStep]]:
        pass

    @abstractmethod
    async def list_computes_in_package(
        self, package_id: int, compute_type: BiGraphComputeType
    ) -> list[BiGraphProcess] | list[BiGraphStep]:
        pass

    @abstractmethod
    async def list_all_computes(self, compute_type: BiGraphComputeType | None = None) -> Any:
        pass

    @abstractmethod
    async def delete_bigraph_package(self, package_id: RegisteredPackage) -> None:
        pass

    @abstractmethod
    async def delete_bigraph_compute(self, compute: BiGraphCompute) -> None:
        pass

    @abstractmethod
    async def dependencies_not_in_database(
        self, dependencies: ExperimentPrimaryDependencies
    ) -> ExperimentPrimaryDependencies:
        pass

    @abstractmethod
    async def list_packages_from_dependencies(
        self, dependencies: ExperimentPrimaryDependencies
    ) -> list[RegisteredPackage]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class PackageORMExecutor(PackageDatabaseService):
    async_session_maker: async_sessionmaker[AsyncSession]

    def __init__(self, async_engine_session_maker: async_sessionmaker[AsyncSession]) -> None:
        self.async_session_maker = async_engine_session_maker

    @staticmethod
    async def _insert_compute(
        session: AsyncSession, compute: BiGraphComputeOutline, package: ORMPackage
    ) -> ORMBiGraphCompute:
        new_orm_process = ORMBiGraphCompute(
            module=compute.module,
            name=compute.name,
            compute_type=BiGraphComputeTypeDB.from_compute_type(compute.compute_type),
            inputs=compute.inputs,
            outputs=compute.outputs,
            package_ref=package.id,
        )
        session.add(new_orm_process)
        return new_orm_process

    @override
    async def insert_package(self, package: PackageOutline) -> RegisteredPackage:
        """
        Package name and origin type must be unique,
        and not inserted in the table already otherwise an error will be raised.
        Args:
            package:

        Returns: RegisteredPackage

        """
        async with self.async_session_maker() as session, session.begin():
            new_orm_package = ORMPackage(
                package_type=PackageTypeDB.from_package_type(package.package_type),
                name=package.name,
            )
            session.add(new_orm_package)
            processes: list[BiGraphProcess] = []
            steps: list[BiGraphStep] = []
            await session.flush()
            for compute in package.compute:
                inserted_compute = await self._insert_compute(session, compute, new_orm_package)
                await session.flush()
                match inserted_compute.compute_type:
                    case BiGraphComputeTypeDB.PROCESS:
                        processes.append(inserted_compute.to_bigraph_process())
                    case BiGraphComputeTypeDB.STEP:
                        steps.append(inserted_compute.to_bigraph_step())
                    case _:
                        raise ValueError(f"Unknown compute type {inserted_compute.compute_type}")

            return new_orm_package.to_bigraph_package(processes, steps)

    async def list_simulator_packages(self, simulator_id: int) -> list[RegisteredPackage]:
        async with self.async_session_maker() as session:
            stmt = (
                select(ORMPackage)
                .join(ORMSimulatorToPackage, onclause=ORMSimulatorToPackage.package_id == ORMPackage.id)
                .where(ORMSimulatorToPackage.simulator_id == simulator_id)
            )

            result: Result[tuple[ORMPackage]] = await session.execute(stmt)
            orm_packages = result.scalars().all()
            packages: list[RegisteredPackage] = []
            for row in orm_packages:
                processes, steps = await self._list_computes_in_package(row.id)
                packages.append(row.to_bigraph_package(processes=processes, steps=steps))

            return packages

    async def list_all_computes_in_package(self, package_id: int) -> tuple[list[BiGraphProcess], list[BiGraphStep]]:
        return await self._list_computes_in_package(package_id=package_id)

    async def list_computes_in_package(
        self, package_id: int, compute_type: BiGraphComputeType
    ) -> list[BiGraphProcess] | list[BiGraphStep]:
        match compute_type:
            case BiGraphComputeType.PROCESS:
                return (await self._list_computes_in_package(package_id))[0]
            case BiGraphComputeType.STEP:
                return (await self._list_computes_in_package(package_id))[1]
        raise ValueError(f"Compute type {compute_type} not supported")

    async def _list_computes_in_package(self, package_id: int) -> tuple[list[BiGraphProcess], list[BiGraphStep]]:
        async with self.async_session_maker() as session:
            stmt = select(ORMBiGraphCompute).where(ORMBiGraphCompute.package_ref == package_id)

            result: Result[tuple[ORMBiGraphCompute]] = await session.execute(stmt)
            orm_computes = result.scalars().all()

            processes = []
            steps = []
            for compute in orm_computes:
                if compute.compute_type == BiGraphComputeTypeDB.PROCESS:
                    processes.append(compute.to_bigraph_process())
                elif compute.compute_type == BiGraphComputeTypeDB.STEP:
                    steps.append(compute.to_bigraph_step())

            return processes, steps

    @override
    async def list_all_computes(self, compute_type: BiGraphComputeType | None = None) -> Any:
        async with self.async_session_maker() as session:
            stmt = select(ORMBiGraphCompute)
            if compute_type is not None:
                stmt = stmt.where(
                    ORMBiGraphCompute.compute_type == BiGraphComputeTypeDB.from_compute_type(compute_type)
                )
            result: Result[tuple[ORMBiGraphCompute]] = await session.execute(stmt)
            match compute_type:
                case BiGraphComputeType.PROCESS:
                    return [k.to_bigraph_process() for k in result.scalars().all()]
                case BiGraphComputeType.STEP:
                    return [k.to_bigraph_step() for k in result.scalars().all()]
                case _:
                    return [k.to_bigraph_compute() for k in result.scalars().all()]

    @staticmethod
    async def _get_package_by_id(session: AsyncSession, package_id: int) -> ORMPackage | None:
        stmt = select(ORMPackage).where(ORMPackage.id == package_id)
        res: Result[tuple[ORMPackage]] = await session.execute(stmt)
        return res.scalars().one_or_none()

    @staticmethod
    async def _get_compute_by_id(session: AsyncSession, package_id: int) -> ORMBiGraphCompute | None:
        stmt = select(ORMBiGraphCompute).where(ORMBiGraphCompute.id == package_id)
        res: Result[tuple[ORMBiGraphCompute]] = await session.execute(stmt)
        return res.scalars().one_or_none()

    async def delete_bigraph_package(self, package: RegisteredPackage) -> None:
        async with self.async_session_maker() as session, session.begin():
            db_rep = await PackageORMExecutor._get_package_by_id(session, package.database_id)
            if db_rep is None:
                raise ValueError(f"Package id: {package.database_id} not found in database")
            await session.delete(db_rep)

    async def delete_bigraph_compute(self, compute: BiGraphCompute) -> None:
        async with self.async_session_maker() as session, session.begin():
            db_rep = await PackageORMExecutor._get_compute_by_id(session, compute.database_id)
            if db_rep is None:
                raise ValueError(f"Compute id: {compute.database_id} not found in database")
            await session.delete(db_rep)

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
    ) -> list[RegisteredPackage]:
        async with self.async_session_maker() as session:
            packages: list[RegisteredPackage] = []
            for dep_type in (dependencies.pypi_dependencies, dependencies.conda_dependencies):
                stmt = select(ORMPackage).where(ORMPackage.name.in_(dep_type))
                result: Result[tuple[ORMPackage]] = await session.execute(stmt)
                orm_packages = result.scalars().all()
                for row in orm_packages:
                    processes, steps = await self._list_computes_in_package(package_id=row.id)
                    packages.append(row.to_bigraph_package(processes=processes, steps=steps))

            return packages

    @override
    async def close(self) -> None:
        pass
