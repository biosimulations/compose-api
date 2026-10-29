import asyncio
import datetime
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import override

from sqlalchemy import (
    ColumnElement,
    Result,
    Row,
    ScalarSelect,
    Select,
    Subquery,
    and_,
    case,
    delete,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from compose_api.db.services.favorites_db import starred
from compose_api.db.tables.environment_tables import ORMEnvironmentVersion
from compose_api.db.tables.hpc_tables import JobStatusDB, JobTypeDB, ORMHpcRun, ORMSubmission
from compose_api.db.tables.simulator_tables import (
    ORMDownloadedContainers,
    ORMEnvironmentImage,
    ORMSimulation,
    ORMSimulator,
    ORMSimulatorToPackage,
)
from compose_api.favorites import FavoriteKind
from compose_api.simulation.containerization import ContainerizationFileRepr
from compose_api.simulation.hpc_utils import get_singularity_hash, get_slurm_sim_experiment_dir
from compose_api.simulation.models import (
    ContainerEngine,
    DownloadedContainerImage,
    EnvironmentImage,
    HpcRun,
    ImageKind,
    RegisteredPackage,
    RemoteContainerImage,
    Simulation,
    SimulationAccess,
    SimulationRequest,
    SimulationResults,
    SimulatorVersion,
    SubmissionSpec,
    SubmissionState,
    SubmittedSimulation,
    Visibility,
)

logger = logging.getLogger(__name__)


class SimulatorDatabaseService(ABC):
    @abstractmethod
    async def insert_simulator(
        self, singularity_def_rep: ContainerizationFileRepr, packages_used: list[RegisteredPackage] | None = None
    ) -> SimulatorVersion:
        pass

    @abstractmethod
    async def insert_downloaded_simulator(self, remote_container_image: RemoteContainerImage) -> SimulatorVersion:
        pass

    @abstractmethod
    async def get_simulator(self, simulator_id: int) -> SimulatorVersion | None:
        pass

    @abstractmethod
    async def get_downloaded_simulator(self, simulator_id: int) -> DownloadedContainerImage | None:
        pass

    @abstractmethod
    async def record_image(
        self,
        simulator_id: int,
        kind: ImageKind,
        location: str,
        digest: str | None = None,
        size_bytes: int | None = None,
        hpcrun_id: int | None = None,
    ) -> EnvironmentImage:
        """Record an available image of a simulator (docs/plan-environment-builds.md, E3, E4).

        An available record of the same location is kept and marked verified (its missing digest or size filled in);
        one whose digest differs is marked unavailable and a new record added, never rewritten.
        """

    @abstractmethod
    async def get_available_image(self, simulator_id: int, kind: ImageKind) -> EnvironmentImage | None:
        """The newest available image of that kind, or None: "built" means one exists."""

    @abstractmethod
    async def list_images(self, simulator_id: int | None = None) -> list[EnvironmentImage]:
        """Every image record, of one simulator or of all, newest first, available or not."""

    @abstractmethod
    async def set_image_verified(self, image_id: int, available: bool) -> None:
        """Mark an image verified now, available or (its file gone) unavailable."""

    @abstractmethod
    def container_lock(self, container_def_hash: str, poll_s: float = 2.0) -> AbstractAsyncContextManager[None]:
        """Held while a container is fetched or built, so one hash is fetched once.

        Every fetch starts in the API, so the lock lives in the database rather than on the shared
        filesystem (file locks are unreliable across NFS clients) and holds across API replicas.
        """
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
        self,
        sim_request: SimulationRequest,
        experiment_id: str,
        simulator_version: SimulatorVersion,
        owner_sub: str | None = None,
        visibility: Visibility = Visibility.PUBLIC,
        submission: SubmissionSpec | None = None,
        environment_version_id: int | None = None,
    ) -> Simulation:
        """Record the simulation; with ``submission``, also its queued ``requested`` submission (one transaction), whose
        request is ``sim_request`` as given (its paths the staged files)."""
        pass

    @abstractmethod
    async def page_simulations(
        self, query: "SimulationQuery", readable: ColumnElement[bool] | None = None
    ) -> tuple[list["SimulationRow"], int]:
        """Simulations matching ``query`` and ``readable``, newest first, each with its latest run; and the total."""

    @abstractmethod
    async def get_simulation_row(self, simulation_id: int) -> "SimulationRow | None":
        """One simulation with its simulator and latest run, for a listing's detail view."""

    @abstractmethod
    async def simulator_uses(
        self, readable: ColumnElement[bool] | None, also: list[int], only: int | None = None
    ) -> list["SimulatorUse"]:
        """Each simulator that a run matching ``readable`` used, or that is in ``also`` (versions), with how many such
        runs used it and when; ``only``: just that simulator. Newest simulator first."""

    @abstractmethod
    async def get_simulations_access(self, simulation_ids: list[int]) -> list[SimulationAccess]:
        """The owner and visibility of each simulation that exists, in no particular order."""
        pass

    @abstractmethod
    async def get_simulation(self, simulation_id: int) -> SubmittedSimulation | None:
        pass

    @abstractmethod
    async def get_simulation_statuses(self, simulation_ids: list[int]) -> dict[int, str]:
        """Each simulation's status, as a comparison member shows it: its latest run's job status, or `submitting`
        while it has none. Simulations that do not exist are left out."""

    @abstractmethod
    async def get_simulations_experiment_id(self, simulation_id: int) -> str:
        pass

    @abstractmethod
    async def list_simulations_that_use_simulator(self, simulator_id: int) -> list[SubmittedSimulation]:
        pass

    @abstractmethod
    async def delete_simulation(self, simulation_id: int) -> None:
        pass

    @abstractmethod
    async def list_simulations(self) -> list[SubmittedSimulation]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


async def _get_hpc_run_from_correlation_id(session: AsyncSession, correlation_id: str) -> HpcRun | None:
    stmt1 = select(ORMHpcRun).where(ORMHpcRun.correlation_id == correlation_id).limit(1)
    result1: Result[tuple[ORMHpcRun]] = await session.execute(stmt1)
    orm_hpc_job: ORMHpcRun | None = result1.scalars().one_or_none()
    hpc_job: HpcRun | None = None if orm_hpc_job is None else orm_hpc_job.to_hpc_run()
    return hpc_job


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
        self, singularity_def_rep: ContainerizationFileRepr, packages_used: list[RegisteredPackage] | None = None
    ) -> SimulatorVersion:
        """
        Inserts a simulator into the database alongside
        creating intermediate tables which correlate this simulator to its various packages. If packages_used is None,
        then the simulator will have no reference to what's inside it.
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
                        ORMSimulator.container_def_hash == singularity_hash,
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
                container_def=singularity_def_rep.representation,
                container_def_hash=singularity_hash,
                container_engine=ContainerEngine[singularity_def_rep.containerization_engine.name],
            )
            session.add(new_orm_simulator)

            await session.flush()
            if packages_used is not None:
                for package in packages_used:
                    relationship = ORMSimulatorToPackage(
                        simulator_id=new_orm_simulator.id, package_id=package.database_id
                    )
                    session.add(relationship)

            # Ensure the ORM object is inserted and has an ID
            return new_orm_simulator.to_simulator_version()

    async def insert_downloaded_simulator(self, remote_container_image: RemoteContainerImage) -> SimulatorVersion:
        """Record that the container is on the cluster, against the simulator with its definition hash.

        The submission path looks the record up by that simulator's id. A record attached to a new row
        is never found, and every submission then fetched the image again, over the file running jobs
        were mounting. A new simulator row is made only when none has the hash.
        """
        async with self.async_session_maker() as session, session.begin():
            stmt = (
                select(ORMSimulator)
                .where(ORMSimulator.container_def_hash == remote_container_image.container_def_hash)
                .order_by(ORMSimulator.id)
                .limit(1)
            )
            simulator: ORMSimulator | None = (await session.execute(stmt)).scalars().one_or_none()
            if simulator is None:
                simulator = ORMSimulator(
                    container_def=remote_container_image.container_def.representation,
                    container_def_hash=remote_container_image.container_def_hash,
                    container_engine=ContainerEngine[remote_container_image.container_def.containerization_engine.name],
                )
                session.add(simulator)
                await session.flush()
            session.add(
                ORMDownloadedContainers(
                    simulator_id=simulator.id,
                    source_url=remote_container_image.source_url,
                    image_name_and_tag=remote_container_image.image_name_and_tag,
                )
            )

            return simulator.to_simulator_version()

    async def get_downloaded_simulator(self, simulator_id: int) -> DownloadedContainerImage | None:
        async with self.async_session_maker() as session, session.begin():
            stmt1 = (
                select(ORMDownloadedContainers, ORMSimulator)
                .join(ORMSimulator, onclause=ORMSimulator.id == ORMDownloadedContainers.simulator_id)
                .where(ORMDownloadedContainers.simulator_id == simulator_id)
                .limit(1)
            )
            result1: Result[tuple[ORMDownloadedContainers, ORMSimulator]] = await session.execute(stmt1)
            orm_downloaded: Row[tuple[ORMDownloadedContainers, ORMSimulator]] | None = result1.one_or_none()
            if orm_downloaded is None:
                return None
            downloaded_container: DownloadedContainerImage = orm_downloaded[0].to_downloaded_container_image(
                orm_downloaded[1].to_simulator_version()
            )
            return downloaded_container

    @override
    async def get_simulator(self, simulator_id: int) -> SimulatorVersion | None:
        async with self.async_session_maker() as session, session.begin():
            orm_simulator = await self._get_orm_simulator(session, simulator_id=simulator_id)
            if orm_simulator is None:
                return None
            return orm_simulator.to_simulator_version()

    @override
    async def record_image(
        self,
        simulator_id: int,
        kind: ImageKind,
        location: str,
        digest: str | None = None,
        size_bytes: int | None = None,
        hpcrun_id: int | None = None,
    ) -> EnvironmentImage:
        now = datetime.datetime.now()
        async with self.async_session_maker() as session, session.begin():
            stmt = (
                select(ORMEnvironmentImage)
                .where(
                    ORMEnvironmentImage.simulator_id == simulator_id,
                    ORMEnvironmentImage.kind == kind.value,
                    ORMEnvironmentImage.location == location,
                    ORMEnvironmentImage.available.is_(True),
                )
                .order_by(ORMEnvironmentImage.id.desc())
                .with_for_update()
            )
            for existing in (await session.execute(stmt)).scalars().all():
                if digest is None or existing.digest is None or existing.digest == digest:
                    existing.digest = existing.digest or digest
                    existing.size_bytes = existing.size_bytes if existing.size_bytes is not None else size_bytes
                    existing.hpcrun_id = existing.hpcrun_id or hpcrun_id
                    existing.verified_at = now
                    await session.flush()
                    return existing.to_environment_image()
                logger.warning(f"Image {location} changed under record {existing.id}; recording it anew")
                existing.available = False
            image = ORMEnvironmentImage(
                simulator_id=simulator_id,
                kind=kind.value,
                location=location,
                digest=digest,
                size_bytes=size_bytes,
                hpcrun_id=hpcrun_id,
                available=True,
                verified_at=now,
            )
            session.add(image)
            await session.flush()
            await session.refresh(image)
            return image.to_environment_image()

    @override
    async def get_available_image(self, simulator_id: int, kind: ImageKind) -> EnvironmentImage | None:
        async with self.async_session_maker() as session:
            stmt = (
                select(ORMEnvironmentImage)
                .where(
                    ORMEnvironmentImage.simulator_id == simulator_id,
                    ORMEnvironmentImage.kind == kind.value,
                    ORMEnvironmentImage.available.is_(True),
                )
                .order_by(ORMEnvironmentImage.id.desc())
                .limit(1)
            )
            image = (await session.execute(stmt)).scalars().one_or_none()
            return image.to_environment_image() if image is not None else None

    @override
    async def list_images(self, simulator_id: int | None = None) -> list[EnvironmentImage]:
        async with self.async_session_maker() as session:
            stmt = select(ORMEnvironmentImage).order_by(ORMEnvironmentImage.id.desc())
            if simulator_id is not None:
                stmt = stmt.where(ORMEnvironmentImage.simulator_id == simulator_id)
            return [image.to_environment_image() for image in (await session.execute(stmt)).scalars().all()]

    @override
    async def set_image_verified(self, image_id: int, available: bool) -> None:
        now = datetime.datetime.now()
        async with self.async_session_maker() as session, session.begin():
            image = await session.get(ORMEnvironmentImage, image_id)
            if image is not None:
                image.available = available
                image.verified_at = now

    @override
    @asynccontextmanager
    async def container_lock(self, container_def_hash: str, poll_s: float = 2.0) -> AsyncIterator[None]:
        """A Postgres transaction-level advisory lock on the hash, held by an open transaction until exit.

        A fetch takes minutes, so waiters poll with ``pg_try_advisory_xact_lock`` and give their connection
        back between tries: only the holder keeps one, however many submissions are waiting.

        Transaction-level, so there is no unlock step: the lock ends with the transaction, which the session
        commits or rolls back on exit, cancellation included. If the API's connection is lost, Postgres ends
        the session and the lock with it (``SESSION_KEEPALIVES`` sets how soon).
        """
        key = {"key": f"compose_api.container:{container_def_hash}"}
        while True:
            async with self.async_session_maker() as session, session.begin():
                acquired = (
                    await session.execute(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"), key)
                ).scalar_one()
                if acquired:
                    yield
                    return
            await asyncio.sleep(poll_s)

    @override
    async def get_simulator_by_def_hash(self, singularity_def_hash: str) -> SimulatorVersion | None:
        async with self.async_session_maker() as session, session.begin():
            # the oldest row: earlier releases could add rows that repeat a hash
            stmt1 = (
                select(ORMSimulator)
                .where(ORMSimulator.container_def_hash == singularity_def_hash)
                .order_by(ORMSimulator.id)
                .limit(1)
            )
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
            images = select(ORMEnvironmentImage).where(ORMEnvironmentImage.simulator_id == simulator_id)
            for image in (await session.execute(images)).scalars().all():
                await session.delete(image)
            # its environment versions (an environment's default pointing at one is cleared by the foreign key)
            await session.execute(
                delete(ORMEnvironmentVersion).where(ORMEnvironmentVersion.simulator_id == simulator_id)
            )
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
        self,
        sim_request: SimulationRequest,
        experiment_id: str,
        simulator_version: SimulatorVersion,
        owner_sub: str | None = None,
        visibility: Visibility = Visibility.PUBLIC,
        submission: SubmissionSpec | None = None,
        environment_version_id: int | None = None,
    ) -> Simulation:
        async with self.async_session_maker() as session, session.begin():
            orm_simulation = ORMSimulation(
                experiment_id=experiment_id,
                simulator_id=simulator_version.database_id,
                environment_version_id=environment_version_id,
                owner_sub=owner_sub,
                visibility=visibility.value,
                labels=dict(sim_request.labels),
                tags=list(sim_request.tags),
                description=sim_request.description,
            )
            session.add(orm_simulation)
            await session.flush()  # Ensure the ORM object is inserted and has an ID
            if submission is not None:
                session.add(
                    ORMSubmission(
                        simulation_id=orm_simulation.id,
                        state=SubmissionState.REQUESTED.value,
                        queue=submission.queue,
                        priority=submission.priority,
                        requested_by=submission.requested_by,
                        request=sim_request.model_dump(mode="json"),
                        staged_on_store=submission.staged_on_store,
                    )
                )

            simulation = Simulation(
                database_id=orm_simulation.id, sim_request=sim_request, simulator_version=simulator_version
            )
            return simulation

    @override
    async def get_simulation(self, simulation_id: int) -> SubmittedSimulation | None:
        async with self.async_session_maker() as session:
            orm_simulation: ORMSimulation | None = await self._get_orm_simulation(session, simulation_id)
            if orm_simulation is None:
                return None
            orm_simulator: ORMSimulator | None = await self._get_orm_simulator(session, orm_simulation.simulator_id)
            if orm_simulator is None:
                raise Exception(
                    f"Simulation with id {simulation_id} does not have a simulator with id {orm_simulation.simulator_id}"  # noqa: E501
                )

            hpc_run = await _get_hpc_run_from_correlation_id(session, orm_simulation.experiment_id)
            simulation = SubmittedSimulation(
                database_id=orm_simulation.id,
                sim_content=SimulationResults(
                    path_on_server=get_slurm_sim_experiment_dir(orm_simulation.experiment_id)
                ),
                simulator_version=orm_simulator.to_simulator_version(),
                hpc_run=hpc_run,
            )
            return simulation

    @override
    async def page_simulations(
        self, query: "SimulationQuery", readable: ColumnElement[bool] | None = None
    ) -> tuple[list["SimulationRow"], int]:
        return await _page_simulations(self.async_session_maker, query, readable)

    @override
    async def get_simulation_row(self, simulation_id: int) -> "SimulationRow | None":
        return await _get_simulation_row(self.async_session_maker, simulation_id)

    @override
    async def simulator_uses(
        self, readable: ColumnElement[bool] | None, also: list[int], only: int | None = None
    ) -> list["SimulatorUse"]:
        joined = ORMSimulation.simulator_id == ORMSimulator.id
        stmt = (
            select(
                ORMSimulator.id,
                ORMSimulator.created_at,
                ORMSimulator.container_def_hash,
                func.count(ORMSimulation.id),
                func.min(ORMSimulation.created_at),
                func.max(ORMSimulation.created_at),
            )
            .outerjoin(ORMSimulation, joined if readable is None else and_(joined, readable))
            .group_by(ORMSimulator.id)
            .having(or_(func.count(ORMSimulation.id) > 0, ORMSimulator.id.in_(also)))
            .order_by(ORMSimulator.id.desc())
        )
        if only is not None:
            stmt = stmt.where(ORMSimulator.id == only)
        async with self.async_session_maker() as session:
            rows = (await session.execute(stmt)).tuples().all()
        return [SimulatorUse(*row) for row in rows]

    @override
    async def get_simulations_access(self, simulation_ids: list[int]) -> list[SimulationAccess]:
        if not simulation_ids:
            return []
        async with self.async_session_maker() as session:
            result = await session.execute(select(ORMSimulation).where(ORMSimulation.id.in_(simulation_ids)))
            return [orm_simulation.to_simulation_access() for orm_simulation in result.scalars().all()]

    @override
    async def get_simulation_statuses(self, simulation_ids: list[int]) -> dict[int, str]:
        if not simulation_ids:
            return {}
        latest = _latest_runs()
        stmt = (
            select(ORMSimulation.id, ORMHpcRun)
            .outerjoin(latest, latest.c.simulation_id == ORMSimulation.id)
            .outerjoin(ORMHpcRun, ORMHpcRun.id == latest.c.hpcrun_id)
            .where(ORMSimulation.id.in_(simulation_ids))
        )
        async with self.async_session_maker() as session:
            rows = (await session.execute(stmt)).tuples().all()
        return {sid: run.status.to_job_status().value if run is not None else "submitting" for sid, run in rows}

    @override
    async def get_simulations_experiment_id(self, simulation_id: int) -> str:
        async with self.async_session_maker() as session:
            orm_simulation: ORMSimulation | None = await self._get_orm_simulation(session, simulation_id)
            if orm_simulation is None:
                raise LookupError(f"Simulation with id {simulation_id} does not exist")
            return orm_simulation.experiment_id

    @override
    async def list_simulations_that_use_simulator(self, simulator_id: int) -> list[SubmittedSimulation]:
        return await self._list_simulations(simulator_id)

    @override
    async def list_simulations(self) -> list[SubmittedSimulation]:
        return await self._list_simulations()

    @override
    async def delete_simulation(self, simulation_id: int) -> None:
        async with self.async_session_maker() as session, session.begin():
            orm_simulation: ORMSimulation | None = await self._get_orm_simulation(session, simulation_id)
            if orm_simulation is None:
                raise Exception(f"Simulation with id {simulation_id} not found in the database")
            await session.delete(orm_simulation)

    async def _list_simulations(self, simulator_id: int | None = None) -> list[SubmittedSimulation]:
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

            simulations: list[SubmittedSimulation] = []
            for row in orm_simulations:
                orm_simulation, orm_simulator = row.t
                sim_request = SimulationResults(
                    path_on_server=get_slurm_sim_experiment_dir(orm_simulation.experiment_id)
                )
                hpc_run = await _get_hpc_run_from_correlation_id(session, orm_simulation.experiment_id)
                simulation = SubmittedSimulation(
                    database_id=orm_simulation.id,
                    sim_content=sim_request,
                    simulator_version=orm_simulator.to_simulator_version(),
                    hpc_run=hpc_run,
                )
                simulations.append(simulation)

            return simulations

    @override
    async def close(self) -> None:
        pass


# -- listing simulations (GET /simulations) ---------------------------------------------------------------------------

SUBMITTING = "submitting"


@dataclass(frozen=True)
class SimulationQuery:
    status: str | None = None  # a JobStatus value, or "submitting" (no SLURM job yet)
    container_def_hash: str | None = None
    simulator_id: int | None = None
    # it ran in one of these environment versions (by id); None: any or none
    environment_version_ids: list[int] | None = None
    since: datetime.datetime | None = None  # created at or after (UTC)
    labels: dict[str, str] = field(default_factory=dict)  # every one must match
    tags: list[str] = field(default_factory=list)  # every one must be present
    owner_sub: str | None = None  # submitted by this subject, signed in
    favorite_of: str | None = None  # starred by this subject (docs/plan-favorites-and-studies.md, step 2)
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class SimulatorUse:
    """A simulator, and how many runs used it and when (none, for a version no run has used yet)."""

    simulator_id: int
    created_at: datetime.datetime
    container_def_hash: str
    run_count: int
    first_run_at: datetime.datetime | None
    last_run_at: datetime.datetime | None


@dataclass(frozen=True)
class SimulationRow:
    simulation: ORMSimulation
    simulator: ORMSimulator
    run: ORMHpcRun | None
    submission: ORMSubmission | None = None
    position: int | None = None  # its place among queued runs, while `requested`


def _latest_runs() -> Subquery:
    return (
        select(ORMHpcRun.simulation_id, func.max(ORMHpcRun.id).label("hpcrun_id"))
        .where(ORMHpcRun.job_type == JobTypeDB.SIMULATION)
        .group_by(ORMHpcRun.simulation_id)
        .subquery()
    )


def _queue_position() -> ScalarSelect[int]:
    """How many queued runs are ahead of this one, plus one: those the worker would claim first (higher priority, or
    as high and older), while this one is `requested`."""
    ahead = aliased(ORMSubmission)
    mine = ORMSubmission
    return (
        select(func.count() + 1)
        .where(
            ahead.state == SubmissionState.REQUESTED.value,
            or_(
                ahead.priority > mine.priority,
                and_(ahead.priority == mine.priority, ahead.created_at < mine.created_at),
            ),
        )
        .correlate(mine)
        .scalar_subquery()
    )


def _simulation_rows() -> Select[tuple[ORMSimulation, ORMSimulator, ORMHpcRun, ORMSubmission, int]]:
    latest = _latest_runs()
    position = case((ORMSubmission.state == SubmissionState.REQUESTED.value, _queue_position()), else_=None)
    return (
        select(ORMSimulation, ORMSimulator, ORMHpcRun, ORMSubmission, position)
        .join(ORMSimulator, ORMSimulator.id == ORMSimulation.simulator_id)
        .outerjoin(latest, latest.c.simulation_id == ORMSimulation.id)
        .outerjoin(ORMHpcRun, ORMHpcRun.id == latest.c.hpcrun_id)
        .outerjoin(ORMSubmission, ORMSubmission.simulation_id == ORMSimulation.id)
    )


def _simulation_conditions(query: SimulationQuery) -> list[ColumnElement[bool]]:
    """``query``'s conditions on the simulation itself (what it is, who submitted it, when)."""
    conditions: list[ColumnElement[bool]] = []
    if query.simulator_id is not None:
        conditions.append(ORMSimulation.simulator_id == query.simulator_id)
    if query.environment_version_ids is not None:
        conditions.append(ORMSimulation.environment_version_id.in_(query.environment_version_ids))
    if query.since is not None:
        conditions.append(ORMSimulation.created_at >= query.since.astimezone(datetime.UTC).replace(tzinfo=None))
    if query.labels:
        conditions.append(ORMSimulation.labels.contains(query.labels))
    if query.tags:
        conditions.append(ORMSimulation.tags.contains(query.tags))
    if query.owner_sub is not None:
        conditions.append(ORMSimulation.owner_sub == query.owner_sub)
    if query.favorite_of is not None:
        conditions.append(starred(ORMSimulation.id, query.favorite_of, FavoriteKind.SIMULATION))
    return conditions


async def _page_simulations(
    session_maker: async_sessionmaker[AsyncSession], query: SimulationQuery, readable: ColumnElement[bool] | None
) -> tuple[list[SimulationRow], int]:
    """Simulations matching ``query`` and ``readable``, newest first, each with its latest run; and the total."""
    stmt = _simulation_rows().where(*_simulation_conditions(query))
    if readable is not None:
        stmt = stmt.where(readable)
    if query.status == SUBMITTING:
        stmt = stmt.where(ORMHpcRun.id.is_(None))
    elif query.status is not None:
        stmt = stmt.where(ORMHpcRun.status == JobStatusDB(query.status))
    if query.container_def_hash is not None:
        stmt = stmt.where(ORMSimulator.container_def_hash.startswith(query.container_def_hash))
    async with session_maker() as session:
        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        result = await session.execute(stmt.order_by(ORMSimulation.id.desc()).limit(query.limit).offset(query.offset))
        rows = [SimulationRow(*row) for row in result.all()]
    return rows, int(total)


async def _get_simulation_row(
    session_maker: async_sessionmaker[AsyncSession], simulation_id: int
) -> SimulationRow | None:
    async with session_maker() as session:
        found = (await session.execute(_simulation_rows().where(ORMSimulation.id == simulation_id))).one_or_none()
    return SimulationRow(*found) if found is not None else None
