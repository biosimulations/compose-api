"""Environments and their versions (compose_api/db/tables/environment_tables.py)."""

from abc import ABC, abstractmethod
from typing import Any, override

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from compose_api.db.tables.environment_tables import ORMEnvironment, ORMEnvironmentVersion
from compose_api.simulation.models import EnvironmentVersion, VersionState


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
        """The version of ``environment`` whose simulator is ``simulator_id``, made its default: created as the next
        number, ready, when there is none. Until versions are created through the API (docs/plan-environment-
        versions.md, step 4), the deployment's own definition decides the default, as it decided the image before."""

    @abstractmethod
    async def get_version(self, version_id: int) -> EnvironmentVersion | None: ...

    @abstractmethod
    async def get_default(self, environment: str) -> EnvironmentVersion | None: ...

    @abstractmethod
    async def list_versions(self, environment: str) -> list[EnvironmentVersion]:
        """Newest first."""


class EnvironmentsORMExecutor(EnvironmentsDatabaseService):
    def __init__(self, async_session_maker: async_sessionmaker[AsyncSession]):
        self.async_session_maker = async_session_maker

    @staticmethod
    async def _default(session: AsyncSession, environment: str) -> ORMEnvironmentVersion | None:
        query = select(ORMEnvironmentVersion).join(
            ORMEnvironment, ORMEnvironment.default_version_id == ORMEnvironmentVersion.id
        )
        return (await session.execute(query.where(ORMEnvironment.name == environment))).scalar_one_or_none()

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
            current = await self._default(session, environment)
            if current is not None and current.simulator_id == simulator_id:
                return current.to_environment_version()  # every run but the first after a deploy
            # one adopter at a time per environment, across API processes; released at commit
            await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"environment:{environment}"))))
            new_environment = insert(ORMEnvironment).values(name=environment, kind=kind)
            await session.execute(new_environment.on_conflict_do_nothing(index_elements=["name"]))
            version = (
                await session.execute(
                    select(ORMEnvironmentVersion).where(
                        ORMEnvironmentVersion.environment == environment,
                        ORMEnvironmentVersion.simulator_id == simulator_id,
                    )
                )
            ).scalar_one_or_none()
            if version is None:
                last = await session.scalar(
                    select(func.max(ORMEnvironmentVersion.number)).where(
                        ORMEnvironmentVersion.environment == environment
                    )
                )
                version = ORMEnvironmentVersion(
                    environment=environment,
                    number=(last or 0) + 1,
                    state=VersionState.READY.value,
                    simulator_id=simulator_id,
                    image=image,
                    spec=spec,
                    origin=origin,
                )
                session.add(version)
                await session.flush()
            env = await session.get(ORMEnvironment, environment, with_for_update=True)
            if env is not None and env.default_version_id != version.id:
                env.default_version_id = version.id
            await session.flush()
            await session.refresh(version)
            return version.to_environment_version()

    @override
    async def get_version(self, version_id: int) -> EnvironmentVersion | None:
        async with self.async_session_maker() as session:
            version = await session.get(ORMEnvironmentVersion, version_id)
            return version.to_environment_version() if version is not None else None

    @override
    async def get_default(self, environment: str) -> EnvironmentVersion | None:
        async with self.async_session_maker() as session:
            version = await self._default(session, environment)
            return version.to_environment_version() if version is not None else None

    @override
    async def list_versions(self, environment: str) -> list[EnvironmentVersion]:
        async with self.async_session_maker() as session:
            query = (
                select(ORMEnvironmentVersion)
                .where(ORMEnvironmentVersion.environment == environment)
                .order_by(ORMEnvironmentVersion.number.desc())
            )
            return [v.to_environment_version() for v in (await session.execute(query)).scalars()]
