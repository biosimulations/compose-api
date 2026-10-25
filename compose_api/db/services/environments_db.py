"""Environments and their versions (compose_api/db/tables/environment_tables.py)."""

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, override

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from compose_api.db.tables.environment_tables import ORMEnvironment, ORMEnvironmentVersion
from compose_api.simulation.models import (
    EnvironmentVersion,
    EnvironmentVersionDetail,
    EnvironmentVersions,
    VersionState,
)

DEPLOYMENT = "deployment"  # the default is the deployment's own definition, adopted by the run path
API = "api"  # an administrator chose the default; the deployment's definition no longer overrides it


@dataclass(frozen=True)
class VersionSource:
    """What a version is made from: a shared one's spec and lock, a prebuilt one's image."""

    image: str | None = None
    spec: dict[str, Any] | None = None
    origin: str | None = None
    resolved_at: datetime.datetime | None = None
    lock: str | None = None
    lock_sha256: str | None = None
    created_by: str | None = None
    note: str | None = None


class EnvironmentsDatabaseService(ABC):
    @abstractmethod
    async def adopt_deployed(
        self,
        environment: str,
        kind: str,
        simulator_id: int,
        *,
        image: str | None = None,
        spec: dict[str, Any] | None = None,
        origin: str | None = None,
    ) -> EnvironmentVersion:
        """The version a run of ``environment`` uses when it names none. If an administrator chose the default, that
        version. Otherwise the version whose simulator is ``simulator_id`` (the deployment's own definition), made the
        default, and created as the next number, ready, when there is none."""

    @abstractmethod
    async def create_version(
        self, environment: str, kind: str, simulator_id: int, source: VersionSource
    ) -> tuple[EnvironmentVersion, bool]:
        """A new version, `building`, as the next number; or, with False, the existing version of the same simulator
        (the same definition, so the same lock). The default does not move."""

    @abstractmethod
    async def set_state(self, version_id: int, state: VersionState) -> None: ...

    @abstractmethod
    async def set_default(self, environment: str, version_id: int) -> None:
        """Make it the default, as an administrator's choice (``default_source`` `api`)."""

    @abstractmethod
    async def get_version(self, version_id: int) -> EnvironmentVersion | None: ...

    @abstractmethod
    async def get_by_number(self, environment: str, number: int) -> EnvironmentVersionDetail | None: ...

    @abstractmethod
    async def find_by_lock(self, environment: str, lock_sha256: str) -> EnvironmentVersion | None: ...

    @abstractmethod
    async def get_default(self, environment: str) -> EnvironmentVersion | None: ...

    @abstractmethod
    async def get_default_detail(self, environment: str) -> EnvironmentVersionDetail | None: ...

    @abstractmethod
    async def list_versions(self, environment: str) -> list[EnvironmentVersion]:
        """Newest first."""

    @abstractmethod
    async def describe(self, environment: str, kind: str) -> EnvironmentVersions:
        """Its versions and its default (an environment never seen yet has none)."""


class EnvironmentsORMExecutor(EnvironmentsDatabaseService):
    def __init__(self, async_session_maker: async_sessionmaker[AsyncSession]):
        self.async_session_maker = async_session_maker

    @staticmethod
    async def _default(session: AsyncSession, environment: str) -> tuple[ORMEnvironmentVersion | None, str | None]:
        """The default version and where it came from."""
        query = select(ORMEnvironmentVersion, ORMEnvironment.default_source).join(
            ORMEnvironment, ORMEnvironment.default_version_id == ORMEnvironmentVersion.id
        )
        row = (await session.execute(query.where(ORMEnvironment.name == environment))).one_or_none()
        return (row[0], row[1]) if row is not None else (None, None)

    @staticmethod
    async def _lock_environment(session: AsyncSession, environment: str, kind: str) -> None:
        """One writer at a time per environment, across API processes (released at commit); its row created."""
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"environment:{environment}"))))
        new_environment = insert(ORMEnvironment).values(name=environment, kind=kind)
        await session.execute(new_environment.on_conflict_do_nothing(index_elements=["name"]))

    @staticmethod
    async def _next_number(session: AsyncSession, environment: str) -> int:
        last = await session.scalar(
            select(func.max(ORMEnvironmentVersion.number)).where(ORMEnvironmentVersion.environment == environment)
        )
        return (last or 0) + 1

    @staticmethod
    async def _of_simulator(session: AsyncSession, environment: str, simulator_id: int) -> ORMEnvironmentVersion | None:
        query = select(ORMEnvironmentVersion).where(
            ORMEnvironmentVersion.environment == environment, ORMEnvironmentVersion.simulator_id == simulator_id
        )
        return (await session.execute(query)).scalar_one_or_none()

    @override
    async def adopt_deployed(
        self,
        environment: str,
        kind: str,
        simulator_id: int,
        *,
        image: str | None = None,
        spec: dict[str, Any] | None = None,
        origin: str | None = None,
    ) -> EnvironmentVersion:
        async with self.async_session_maker() as session, session.begin():
            current, source = await self._default(session, environment)
            if current is not None and (source == API or current.simulator_id == simulator_id):
                return current.to_environment_version()  # every run but the first after a deploy
            await self._lock_environment(session, environment, kind)
            env = await session.get(ORMEnvironment, environment, with_for_update=True)
            if env is not None and env.default_source == API and env.default_version_id is not None:
                chosen = await session.get(ORMEnvironmentVersion, env.default_version_id)
                if chosen is not None:  # chosen while this one waited for the lock
                    return chosen.to_environment_version()
            version = await self._of_simulator(session, environment, simulator_id)
            if version is None:
                version = ORMEnvironmentVersion(
                    environment=environment,
                    number=await self._next_number(session, environment),
                    state=VersionState.READY.value,
                    simulator_id=simulator_id,
                    image=image,
                    spec=spec,
                    origin=origin,
                )
                session.add(version)
                await session.flush()
            if env is not None and env.default_version_id != version.id:
                env.default_version_id = version.id
                env.default_source = DEPLOYMENT
            await session.flush()
            await session.refresh(version)
            return version.to_environment_version()

    @override
    async def create_version(
        self, environment: str, kind: str, simulator_id: int, source: VersionSource
    ) -> tuple[EnvironmentVersion, bool]:
        async with self.async_session_maker() as session, session.begin():
            await self._lock_environment(session, environment, kind)
            existing = await self._of_simulator(session, environment, simulator_id)
            if existing is not None:
                return existing.to_environment_version(), False
            version = ORMEnvironmentVersion(
                environment=environment,
                number=await self._next_number(session, environment),
                state=VersionState.BUILDING.value,
                simulator_id=simulator_id,
                image=source.image,
                spec=source.spec,
                origin=source.origin,
                resolved_at=source.resolved_at,
                lock=source.lock,
                lock_sha256=source.lock_sha256,
                created_by=source.created_by,
                note=source.note,
            )
            session.add(version)
            await session.flush()
            await session.refresh(version)
            return version.to_environment_version(), True

    @override
    async def set_state(self, version_id: int, state: VersionState) -> None:
        async with self.async_session_maker() as session, session.begin():
            query = update(ORMEnvironmentVersion).where(ORMEnvironmentVersion.id == version_id)
            await session.execute(query.values(state=state.value))

    @override
    async def set_default(self, environment: str, version_id: int) -> None:
        async with self.async_session_maker() as session, session.begin():
            query = update(ORMEnvironment).where(ORMEnvironment.name == environment)
            await session.execute(query.values(default_version_id=version_id, default_source=API))

    @override
    async def get_version(self, version_id: int) -> EnvironmentVersion | None:
        async with self.async_session_maker() as session:
            version = await session.get(ORMEnvironmentVersion, version_id)
            return version.to_environment_version() if version is not None else None

    @override
    async def get_by_number(self, environment: str, number: int) -> EnvironmentVersionDetail | None:
        async with self.async_session_maker() as session:
            query = select(ORMEnvironmentVersion).where(
                ORMEnvironmentVersion.environment == environment, ORMEnvironmentVersion.number == number
            )
            version = (await session.execute(query)).scalar_one_or_none()
            return version.to_environment_version_detail() if version is not None else None

    @override
    async def find_by_lock(self, environment: str, lock_sha256: str) -> EnvironmentVersion | None:
        async with self.async_session_maker() as session:
            query = select(ORMEnvironmentVersion).where(
                ORMEnvironmentVersion.environment == environment, ORMEnvironmentVersion.lock_sha256 == lock_sha256
            )
            version = (await session.execute(query.limit(1))).scalar_one_or_none()
            return version.to_environment_version() if version is not None else None

    @override
    async def get_default(self, environment: str) -> EnvironmentVersion | None:
        async with self.async_session_maker() as session:
            version, _ = await self._default(session, environment)
            return version.to_environment_version() if version is not None else None

    @override
    async def get_default_detail(self, environment: str) -> EnvironmentVersionDetail | None:
        async with self.async_session_maker() as session:
            version, _ = await self._default(session, environment)
            return version.to_environment_version_detail() if version is not None else None

    @override
    async def list_versions(self, environment: str) -> list[EnvironmentVersion]:
        async with self.async_session_maker() as session:
            query = (
                select(ORMEnvironmentVersion)
                .where(ORMEnvironmentVersion.environment == environment)
                .order_by(ORMEnvironmentVersion.number.desc())
            )
            return [v.to_environment_version() for v in (await session.execute(query)).scalars()]

    @override
    async def describe(self, environment: str, kind: str) -> EnvironmentVersions:
        async with self.async_session_maker() as session:
            default, source = await self._default(session, environment)
        return EnvironmentVersions(
            environment=environment,
            kind=kind,
            default=default.number if default is not None else None,
            default_source=source or DEPLOYMENT,
            versions=await self.list_versions(environment),
        )
