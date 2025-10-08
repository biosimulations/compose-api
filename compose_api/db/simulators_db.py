import logging
from abc import ABC, abstractmethod

from sqlalchemy import Result, and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from compose_api.btools.bsander.bsandr_utils.input_types import ContainerizationFileRepr
from compose_api.db.tables_orm import (
    BiGraphEdgeTypeDB,
    ORMBiGraphEdge,
    ORMPackage,
    ORMPackageToEdge,
    ORMSimulation,
    ORMSimulator,
    ORMSimulatorToPackage,
    PackageTypeDB,
)
from compose_api.simulation.hpc_utils import get_singularity_hash, get_slurm_sim_experiment_dir
from compose_api.simulation.models import (
    BiGraphEdge,
    BiGraphEdgeType,
    BiGraphPackage,
    BiGraphProcess,
    BiGraphStep,
    PackageOutline,
    Simulation,
    SimulationRequest,
    SimulatorVersion,
)

logger = logging.getLogger(__name__)


class SimulatorDB(ABC):
    @abstractmethod
    async def insert_simulator(
        self, singularity_def_rep: ContainerizationFileRepr, packages: list[PackageOutline]
    ) -> SimulatorVersion:
        pass

    @abstractmethod
    async def get_simulator(self, simulator_id: int) -> SimulatorVersion | None:
        pass

    @abstractmethod
    async def get_simulator_by_def_hash(self, singularity_def_hash: str) -> SimulatorVersion | None:
        pass

    @abstractmethod
    async def delete_simulator(self, simulator_id: int) -> None:
        pass

    @abstractmethod
    async def list_simulators(self) -> list[SimulatorVersion]:
        pass

    @abstractmethod
    async def insert_simulation(
        self, sim_request: SimulationRequest, experiment_id: str, simulator_version: SimulatorVersion
    ) -> Simulation:
        pass

    @abstractmethod
    async def get_simulation(self, simulation_id: int) -> Simulation | None:
        pass

    @abstractmethod
    async def list_simulations_that_use_simulator(self, simulator_id: int) -> list[Simulation]:
        pass

    @abstractmethod
    async def delete_simulation(self, simulation_id: int) -> None:
        pass

    @abstractmethod
    async def list_simulations(self) -> list[Simulation]:
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
    async def close(self) -> None:
        pass


class SimulatorDBSQL(SimulatorDB):
    async_session_maker: async_sessionmaker[AsyncSession]

    def __init__(self, async_engine_session_maker: async_sessionmaker[AsyncSession]) -> None:
        self.async_session_maker = async_engine_session_maker

    @staticmethod
    async def _get_orm_simulator(session: AsyncSession, simulator_id: int) -> ORMSimulator | None:
        stmt1 = select(ORMSimulator).where(ORMSimulator.id == simulator_id).limit(1)
        result1: Result[tuple[ORMSimulator]] = await session.execute(stmt1)
        orm_simulator: ORMSimulator | None = result1.scalars().one_or_none()
        return orm_simulator

    @staticmethod
    async def _get_orm_simulation(session: AsyncSession, simulation_id: int) -> ORMSimulation | None:
        stmt1 = select(ORMSimulation).where(ORMSimulation.id == simulation_id).limit(1)
        result1: Result[tuple[ORMSimulation]] = await session.execute(stmt1)
        orm_simulation: ORMSimulation | None = result1.scalars().one_or_none()
        return orm_simulation

    @override
    async def insert_simulator(
        self, singularity_def_rep: ContainerizationFileRepr, packages: list[PackageOutline]
    ) -> SimulatorVersion:
        async with self.async_session_maker() as session, session.begin():
            singularity_hash = get_singularity_hash(singularity_def_rep)
            stmt1 = (
                select(ORMSimulator)
                .where(
                    and_(
                        ORMSimulator.singularity_def_hash == singularity_hash,
                    )
                )
                .limit(1)
            )
            result1: Result[tuple[ORMSimulator]] = await session.execute(stmt1)
            existing_orm_simulator: ORMSimulator | None = result1.scalars().one_or_none()
            if existing_orm_simulator is not None:
                # If the simulator already exists
                logger.error(f"Simulator with singularity_def_hash={singularity_hash}, already exists in the database")
                raise RuntimeError(
                    f"Simulator with singularity_def_hash={singularity_hash} already exists in the database"
                )

            # did not find the simulator, so insert it
            new_orm_simulator = ORMSimulator(
                singularity_def=singularity_def_rep.representation,
                singularity_def_hash=singularity_hash,
            )
            session.add(new_orm_simulator)

            orm_packages: list[ORMPackage] = []
            for package in packages:
                orm_packages.append(await self._insert_package(session, package))

            await session.flush()
            for orm_package in orm_packages:
                relationship = ORMSimulatorToPackage(simulator_id=new_orm_simulator.id, package_id=orm_package.id)
                session.add(relationship)

            # Ensure the ORM object is inserted and has an ID
            return new_orm_simulator.to_simulator_version()

    async def _insert_package(self, session: AsyncSession, package: PackageOutline) -> ORMPackage:
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
            relationship = ORMPackageToEdge(package_id=new_orm_package.id, process_id=orm_process.id)
            session.add(relationship)
        return new_orm_package

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
    async def get_simulator(self, simulator_id: int) -> SimulatorVersion | None:
        async with self.async_session_maker() as session, session.begin():
            orm_simulator = await self._get_orm_simulator(session, simulator_id=simulator_id)
            if orm_simulator is None:
                return None
            return orm_simulator.to_simulator_version()

    @override
    async def get_simulator_by_def_hash(self, singularity_def_hash: str) -> SimulatorVersion | None:
        async with self.async_session_maker() as session, session.begin():
            stmt1 = select(ORMSimulator).where(ORMSimulator.singularity_def_hash == singularity_def_hash).limit(1)
            result1: Result[tuple[ORMSimulator]] = await session.execute(stmt1)
            orm_simulator: ORMSimulator | None = result1.scalars().one_or_none()
            if orm_simulator is None:
                return None
            return orm_simulator.to_simulator_version()

    @override
    async def delete_simulator(self, simulator_id: int) -> None:
        async with self.async_session_maker() as session, session.begin():
            orm_simulator: ORMSimulator | None = await self._get_orm_simulator(session, simulator_id=simulator_id)
            if orm_simulator is None:
                raise Exception(f"Simulator with id {simulator_id} not found in the database")
            await session.delete(orm_simulator)

    @override
    async def list_simulators(self) -> list[SimulatorVersion]:
        async with self.async_session_maker() as session:
            stmt = select(ORMSimulator)
            result: Result[tuple[ORMSimulator]] = await session.execute(stmt)
            orm_simulators = result.scalars().all()

            simulator_versions: list[SimulatorVersion] = []
            for orm_simulator in orm_simulators:
                simulator_versions.append(orm_simulator.to_simulator_version())
            return simulator_versions

    @override
    async def insert_simulation(
        self, sim_request: SimulationRequest, experiment_id: str, simulator_version: SimulatorVersion
    ) -> Simulation:
        async with self.async_session_maker() as session, session.begin():
            orm_simulation = ORMSimulation(experiment_id=experiment_id, simulator_id=simulator_version.database_id)
            session.add(orm_simulation)
            await session.flush()  # Ensure the ORM object is inserted and has an ID

            simulation = Simulation(
                database_id=orm_simulation.id, sim_request=sim_request, simulator_version=simulator_version
            )
            return simulation

    @override
    async def get_simulation(self, simulation_id: int) -> Simulation | None:
        async with self.async_session_maker() as session:
            orm_simulation: ORMSimulation | None = await self._get_orm_simulation(session, simulation_id)
            if orm_simulation is None:
                return None
            orm_simulator: ORMSimulator | None = await self._get_orm_simulator(session, orm_simulation.simulator_id)
            if orm_simulator is None:
                raise Exception(
                    f"Simulation with id {simulation_id} does not have a simulator with id {orm_simulation.simulator_id}"  # noqa: E501
                )

            sim_request = SimulationRequest(omex_archive=get_slurm_sim_experiment_dir(orm_simulation.experiment_id))

            simulation = Simulation(
                database_id=orm_simulation.id,
                sim_request=sim_request,
                simulator_version=orm_simulator.to_simulator_version(),
            )
            return simulation

    @override
    async def list_simulations_that_use_simulator(self, simulator_id: int) -> list[Simulation]:
        return await self._list_simulations(simulator_id)

    @override
    async def list_simulations(self) -> list[Simulation]:
        return await self._list_simulations()

    @override
    async def delete_simulation(self, simulation_id: int) -> None:
        async with self.async_session_maker() as session, session.begin():
            orm_simulation: ORMSimulation | None = await self._get_orm_simulation(session, simulation_id)
            if orm_simulation is None:
                raise Exception(f"Simulation with id {simulation_id} not found in the database")
            await session.delete(orm_simulation)

    async def _list_simulations(self, simulator_id: int | None = None) -> list[Simulation]:
        async with self.async_session_maker() as session:
            if simulator_id is None:
                stmt = select(ORMSimulation, ORMSimulator).join(
                    ORMSimulator, onclause=ORMSimulation.simulator_id == ORMSimulator.id
                )
            else:
                stmt = (
                    select(ORMSimulation, ORMSimulator)
                    .join(ORMSimulator, onclause=ORMSimulation.simulator_id == ORMSimulator.id)
                    .where(ORMSimulator.id == simulator_id)
                )
            result: Result[tuple[ORMSimulation, ORMSimulator]] = await session.execute(stmt)
            orm_simulations = result.fetchall()

            simulations: list[Simulation] = []
            for row in orm_simulations:
                orm_simulation, orm_simulator = row.t
                sim_request = SimulationRequest(omex_archive=get_slurm_sim_experiment_dir(orm_simulation.experiment_id))
                simulation = Simulation(
                    database_id=orm_simulation.id,
                    sim_request=sim_request,
                    simulator_version=orm_simulator.to_simulator_version(),
                )
                simulations.append(simulation)

            return simulations

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

    @override
    async def close(self) -> None:
        pass
