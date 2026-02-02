import logging
from abc import ABC, abstractmethod

from pbest.utils.input_types import ContainerizationFileRepr
from sqlalchemy import Result, and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from compose_api.db.tables.simulator_tables import (
    ORMSimulation,
    ORMSimulator,
    ORMSimulatorToPackage,
)
from compose_api.simulation.hpc_utils import get_singularity_hash, get_slurm_sim_experiment_dir
from compose_api.simulation.models import (
    RegisteredPackage,
    Simulation,
    SimulationRequest,
    SimulatorVersion,
)

logger = logging.getLogger(__name__)


class SimulatorDatabaseService(ABC):
    @abstractmethod
    async def insert_simulator(
        self, singularity_def_rep: ContainerizationFileRepr, packages_used: list[RegisteredPackage]
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
    async def get_simulations_experiment_id(self, simulation_id: int) -> str:
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
    async def close(self) -> None:
        pass


class SimulatorORMExecutor(SimulatorDatabaseService):
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
        self, singularity_def_rep: ContainerizationFileRepr, packages_used: list[RegisteredPackage]
    ) -> SimulatorVersion:
        """
        Inserts a simulator into the database alongside
        creating intermediate tables which correlate this simulator to its various packages.
        Args:
            singularity_def_rep:
            packages_used:

        Returns: SimulatorVersion

        """
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

            await session.flush()
            for package in packages_used:
                relationship = ORMSimulatorToPackage(simulator_id=new_orm_simulator.id, package_id=package.database_id)
                session.add(relationship)

            # Ensure the ORM object is inserted and has an ID
            return new_orm_simulator.to_simulator_version()

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
        """
        Remove both the simulator and the intermediate links this simulator has to various packages in the DB.
        Args:
            simulator_id:

        Returns:
        """
        async with self.async_session_maker() as session, session.begin():
            orm_simulator: ORMSimulator | None = await self._get_orm_simulator(session, simulator_id=simulator_id)
            if orm_simulator is None:
                raise Exception(f"Simulator with id {simulator_id} not found in the database")
            stmt = select(ORMSimulatorToPackage).where(ORMSimulatorToPackage.simulator_id == simulator_id)
            rst = (await session.execute(stmt)).scalars().all()
            for k in rst:
                await session.delete(k)
            await session.flush()
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
    async def get_simulations_experiment_id(self, simulation_id: int) -> str:
        async with self.async_session_maker() as session:
            orm_simulation: ORMSimulation | None = await self._get_orm_simulation(session, simulation_id)
            if orm_simulation is None:
                raise LookupError(f"Simulation with id {simulation_id} does not exist")
            return orm_simulation.experiment_id

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

    @override
    async def close(self) -> None:
        pass
