import datetime
import logging
from abc import ABC, abstractmethod

from sqlalchemy import Result, and_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute
from typing_extensions import override

from compose_api.btools.bsander.bsandr_utils.input_types import ContainerizationFileRepr, ExperimentPrimaryDependencies
from compose_api.common.hpc.models import SlurmJob
from compose_api.db.tables_orm import (
    JobStatusDB,
    JobTypeDB,
    ORMHpcRun,
    ORMSimulation,
    ORMSimulator,
    ORMWorkerEvent,
)
from compose_api.simulation.hpc_utils import get_singularity_hash, get_slurm_sim_experiment_dir
from compose_api.simulation.models import (
    HpcRun,
    JobType,
    Simulation,
    SimulationRequest,
    SimulatorVersion,
    WorkerEvent,
)

logger = logging.getLogger(__name__)


class DatabaseService(ABC):
    @abstractmethod
    async def insert_worker_event(self, worker_event: WorkerEvent, hpcrun_id: int) -> WorkerEvent:
        pass

    @abstractmethod
    async def list_worker_events(self, hpcrun_id: int, prev_sequence_number: int | None = None) -> list[WorkerEvent]:
        pass

    @abstractmethod
    async def insert_simulator(
        self, singularity_def_rep: ContainerizationFileRepr, experiment_dependencies: ExperimentPrimaryDependencies
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
    async def insert_hpcrun(self, slurmjobid: int, job_type: JobType, ref_id: int, correlation_id: str) -> HpcRun:
        """
        :param slurmjobid: (`int`) slurm job id for the associated `job_type`.
        :param job_type: (`JobType`) job type to be run. Choose one of the following:
            `JobType.SIMULATION`
        :param ref_id: primary key of the object this HPC run is associated with (sim, etc.).
        """
        pass

    @abstractmethod
    async def get_hpcrun_by_ref(self, ref_id: int, job_type: JobType) -> HpcRun | None:
        pass

    @abstractmethod
    async def get_hpcrun_by_slurmjobid(self, slurmjobid: int) -> HpcRun | None:
        pass

    @abstractmethod
    async def get_hpcrun(self, hpcrun_id: int) -> HpcRun | None:
        pass

    @abstractmethod
    async def get_hpcrun_id_by_correlation_id(self, correlation_id: str) -> int | None:
        pass

    @abstractmethod
    async def delete_hpcrun(self, hpcrun_id: int) -> None:
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
    async def list_running_hpcruns(self) -> list[HpcRun]:
        """Return all HpcRun jobs with status RUNNING."""
        pass

    @abstractmethod
    async def update_hpcrun_status(self, hpcrun_id: int, new_slurm_job: SlurmJob) -> None:
        """Update the status of a given HpcRun job."""
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class DatabaseServiceSQL(DatabaseService):
    async_sessionmaker: async_sessionmaker[AsyncSession]

    def __init__(self, async_engine: AsyncEngine):
        self.async_sessionmaker = async_sessionmaker(async_engine, expire_on_commit=True)

    async def _get_orm_simulator(self, session: AsyncSession, simulator_id: int) -> ORMSimulator | None:
        stmt1 = select(ORMSimulator).where(ORMSimulator.id == simulator_id).limit(1)
        result1: Result[tuple[ORMSimulator]] = await session.execute(stmt1)
        orm_simulator: ORMSimulator | None = result1.scalars().one_or_none()
        return orm_simulator

    async def _get_orm_simulation(self, session: AsyncSession, simulation_id: int) -> ORMSimulation | None:
        stmt1 = select(ORMSimulation).where(ORMSimulation.id == simulation_id).limit(1)
        result1: Result[tuple[ORMSimulation]] = await session.execute(stmt1)
        orm_simulation: ORMSimulation | None = result1.scalars().one_or_none()
        return orm_simulation

    async def _get_orm_hpcrun(self, session: AsyncSession, hpcrun_id: int) -> ORMHpcRun | None:
        stmt1 = select(ORMHpcRun).where(ORMHpcRun.id == hpcrun_id).limit(1)
        result1: Result[tuple[ORMHpcRun]] = await session.execute(stmt1)
        orm_hpc_job: ORMHpcRun | None = result1.scalars().one_or_none()
        return orm_hpc_job

    async def _get_orm_hpcrun_by_slurmjobid(self, session: AsyncSession, slurmjobid: int) -> ORMHpcRun | None:
        stmt1 = select(ORMHpcRun).where(ORMHpcRun.slurmjobid == slurmjobid).limit(1)
        result1: Result[tuple[ORMHpcRun]] = await session.execute(stmt1)
        orm_hpc_job: ORMHpcRun | None = result1.scalars().one_or_none()
        return orm_hpc_job

    def _get_job_type_ref(self, job_type: JobType) -> InstrumentedAttribute[int | None]:
        match job_type:
            case JobType.SIMULATION:
                return ORMHpcRun.jobref_simulation_id

    async def _get_orm_hpcrun_by_ref(self, session: AsyncSession, ref_id: int, job_type: JobType) -> ORMHpcRun | None:
        reference = self._get_job_type_ref(job_type)
        stmt1 = select(ORMHpcRun).where(reference == ref_id).limit(1)
        result1: Result[tuple[ORMHpcRun]] = await session.execute(stmt1)
        orm_hpc_job: ORMHpcRun | None = result1.scalars().one_or_none()

        return orm_hpc_job

    @override
    async def insert_simulator(
        self, singularity_def_rep: ContainerizationFileRepr, experiment_dependencies: ExperimentPrimaryDependencies
    ) -> SimulatorVersion:
        async with self.async_sessionmaker() as session, session.begin():
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
                primary_packages=experiment_dependencies.get_compact_repr(),
            )
            session.add(new_orm_simulator)
            await session.flush()
            # Ensure the ORM object is inserted and has an ID
            return new_orm_simulator.to_simulator_version()

    @override
    async def get_simulator(self, simulator_id: int) -> SimulatorVersion | None:
        async with self.async_sessionmaker() as session, session.begin():
            orm_simulator = await self._get_orm_simulator(session, simulator_id=simulator_id)
            if orm_simulator is None:
                return None
            return orm_simulator.to_simulator_version()

    @override
    async def get_simulator_by_def_hash(self, singularity_def_hash: str) -> SimulatorVersion | None:
        async with self.async_sessionmaker() as session, session.begin():
            stmt1 = select(ORMSimulator).where(ORMSimulator.singularity_def_hash == singularity_def_hash).limit(1)
            result1: Result[tuple[ORMSimulator]] = await session.execute(stmt1)
            orm_simulator: ORMSimulator | None = result1.scalars().one_or_none()
            if orm_simulator is None:
                return None
            return orm_simulator.to_simulator_version()

    @override
    async def delete_simulator(self, simulator_id: int) -> None:
        async with self.async_sessionmaker() as session, session.begin():
            orm_simulator: ORMSimulator | None = await self._get_orm_simulator(session, simulator_id=simulator_id)
            if orm_simulator is None:
                raise Exception(f"Simulator with id {simulator_id} not found in the database")
            await session.delete(orm_simulator)

    @override
    async def list_simulators(self) -> list[SimulatorVersion]:
        async with self.async_sessionmaker() as session:
            stmt = select(ORMSimulator)
            result: Result[tuple[ORMSimulator]] = await session.execute(stmt)
            orm_simulators = result.scalars().all()

            simulator_versions: list[SimulatorVersion] = []
            for orm_simulator in orm_simulators:
                simulator_versions.append(orm_simulator.to_simulator_version())
            return simulator_versions

    @override
    async def insert_hpcrun(self, slurmjobid: int, job_type: JobType, ref_id: int, correlation_id: str) -> HpcRun:
        jobref_simulation_id = ref_id if job_type == JobType.SIMULATION else None
        async with self.async_sessionmaker() as session, session.begin():
            orm_hpc_run = ORMHpcRun(
                slurmjobid=slurmjobid,
                job_type=JobTypeDB.from_job_type(job_type),
                status=JobStatusDB.RUNNING,
                jobref_simulation_id=jobref_simulation_id,
                start_time=datetime.datetime.now(),
                correlation_id=correlation_id,
            )
            session.add(orm_hpc_run)
            await session.flush()
            return orm_hpc_run.to_hpc_run()

    @override
    async def get_hpcrun_by_slurmjobid(self, slurmjobid: int) -> HpcRun | None:
        async with self.async_sessionmaker() as session, session.begin():
            orm_hpc_job: ORMHpcRun | None = await self._get_orm_hpcrun_by_slurmjobid(session, slurmjobid=slurmjobid)
            if orm_hpc_job is None:
                return None
            return orm_hpc_job.to_hpc_run()

    @override
    async def get_hpcrun_by_ref(self, ref_id: int, job_type: JobType) -> HpcRun | None:
        async with self.async_sessionmaker() as session, session.begin():
            orm_hpc_job: ORMHpcRun | None = await self._get_orm_hpcrun_by_ref(session, ref_id=ref_id, job_type=job_type)
            if orm_hpc_job is None:
                return None
            return orm_hpc_job.to_hpc_run()

    @override
    async def get_hpcrun(self, hpcrun_id: int) -> HpcRun | None:
        async with self.async_sessionmaker() as session, session.begin():
            orm_hpc_job: ORMHpcRun | None = await self._get_orm_hpcrun(session, hpcrun_id=hpcrun_id)
            if orm_hpc_job is None:
                return None
            return orm_hpc_job.to_hpc_run()

    @override
    async def delete_hpcrun(self, hpcrun_id: int) -> None:
        async with self.async_sessionmaker() as session, session.begin():
            hpcrun: ORMHpcRun | None = await self._get_orm_hpcrun(session, hpcrun_id=hpcrun_id)
            if hpcrun is None:
                raise Exception(f"HpcRun with id {hpcrun_id} not found in the database")
            await session.delete(hpcrun)

    @override
    async def insert_worker_event(self, worker_event: WorkerEvent, hpcrun_id: int) -> WorkerEvent:
        async with self.async_sessionmaker() as session, session.begin():
            orm_worker_event = ORMWorkerEvent.from_worker_event(worker_event, hpcrun_id=hpcrun_id)
            session.add(orm_worker_event)
            await session.flush()  # Ensure the ORM object is inserted and has an ID

            new_worker_event = orm_worker_event.to_worker_event()
            return new_worker_event

    @override
    async def list_worker_events(self, hpcrun_id: int, prev_sequence_number: int | None = None) -> list[WorkerEvent]:
        async with self.async_sessionmaker() as session, session.begin():
            stmt = (
                select(
                    ORMWorkerEvent.mass,
                    ORMWorkerEvent.sequence_number,
                    ORMWorkerEvent.id,
                    ORMWorkerEvent.time,
                    ORMWorkerEvent.hpcrun_id,
                )
                .where(
                    and_(
                        ORMWorkerEvent.hpcrun_id == hpcrun_id,
                        ORMWorkerEvent.sequence_number > (prev_sequence_number or -1),
                    )
                )
                .order_by(ORMWorkerEvent.sequence_number)
            )
            result: Result[tuple[dict[str, float], int, int, float, int]] = await session.execute(stmt)
            orm_worker_events = result.all()

            worker_events: list[WorkerEvent] = []
            for orm_worker_event in orm_worker_events:
                worker_events.append(ORMWorkerEvent.from_query_results(orm_worker_event.tuple()))
            return worker_events

    @override
    async def insert_simulation(
        self, sim_request: SimulationRequest, experiment_id: str, simulator_version: SimulatorVersion
    ) -> Simulation:
        async with self.async_sessionmaker() as session, session.begin():
            orm_simulation = ORMSimulation(experiment_id=experiment_id, simulator_id=simulator_version.database_id)
            session.add(orm_simulation)
            await session.flush()  # Ensure the ORM object is inserted and has an ID

            simulation = Simulation(
                database_id=orm_simulation.id, sim_request=sim_request, simulator_version=simulator_version
            )
            return simulation

    @override
    async def get_simulation(self, simulation_id: int) -> Simulation | None:
        async with self.async_sessionmaker() as session:
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
        async with self.async_sessionmaker() as session, session.begin():
            orm_simulation: ORMSimulation | None = await self._get_orm_simulation(session, simulation_id)
            if orm_simulation is None:
                raise Exception(f"Simulation with id {simulation_id} not found in the database")
            await session.delete(orm_simulation)

    async def _list_simulations(self, simulator_id: int | None = None) -> list[Simulation]:
        async with self.async_sessionmaker() as session:
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
    async def list_running_hpcruns(self) -> list[HpcRun]:
        async with self.async_sessionmaker() as session:
            stmt = select(ORMHpcRun).where(ORMHpcRun.status == JobStatusDB.RUNNING)
            result: Result[tuple[ORMHpcRun]] = await session.execute(stmt)
            orm_hpcruns = result.scalars().all()
            return [orm_hpcrun.to_hpc_run() for orm_hpcrun in orm_hpcruns]

    @override
    async def update_hpcrun_status(self, hpcrun_id: int, new_slurm_job: SlurmJob) -> None:
        async with self.async_sessionmaker() as session, session.begin():
            orm_hpcrun: ORMHpcRun | None = await self._get_orm_hpcrun(session, hpcrun_id=hpcrun_id)
            if orm_hpcrun is None:
                raise Exception(f"HpcRun with id {hpcrun_id} not found in the database")
            orm_hpcrun.status = JobStatusDB(new_slurm_job.job_state.lower())
            if new_slurm_job.start_time is not None and new_slurm_job.start_time != orm_hpcrun.start_time:
                orm_hpcrun.start_time = datetime.datetime.fromisoformat(new_slurm_job.start_time)
            if new_slurm_job.end_time is not None and new_slurm_job.end_time != orm_hpcrun.end_time:
                orm_hpcrun.end_time = datetime.datetime.fromisoformat(new_slurm_job.end_time)
            await session.flush()

    @override
    async def get_hpcrun_id_by_correlation_id(self, correlation_id: str) -> int | None:
        async with self.async_sessionmaker() as session, session.begin():
            stmt = select(ORMHpcRun.id).where(ORMHpcRun.correlation_id == correlation_id).limit(1)
            result: Result[tuple[int]] = await session.execute(stmt)
            orm_hpcrun_id: int | None = result.scalar_one_or_none()
            return orm_hpcrun_id

    @override
    async def close(self) -> None:
        pass
