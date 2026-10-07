import logging
from abc import ABC, abstractmethod
from typing import override

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from compose_api.db.services.datasets_db import DatasetsDatabaseService, DatasetsORMExecutor
from compose_api.db.services.events_db import EventsDatabaseService, EventsORMExecutor
from compose_api.db.services.hpc_db import HPCDatabaseService, HPCORMExecutor
from compose_api.db.services.packages_db import PackageDatabaseService, PackageORMExecutor
from compose_api.db.services.simulators_db import SimulatorDatabaseService, SimulatorORMExecutor

logger = logging.getLogger(__name__)


class DatabaseService(ABC):
    @abstractmethod
    def get_simulator_db(self) -> SimulatorDatabaseService:
        pass

    @abstractmethod
    def get_hpc_db(self) -> HPCDatabaseService:
        pass

    @abstractmethod
    def get_package_db(self) -> PackageDatabaseService:
        pass

    @abstractmethod
    def get_events_db(self) -> EventsDatabaseService:
        pass

    @abstractmethod
    def get_datasets_db(self) -> DatasetsDatabaseService:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class DatabaseServiceSQL(DatabaseService):
    async_sessionmaker: async_sessionmaker[AsyncSession]
    simulator_db: SimulatorDatabaseService
    hpc_database: HPCDatabaseService
    package_db: PackageDatabaseService
    events_db: EventsDatabaseService
    datasets_db: DatasetsDatabaseService

    def __init__(self, async_engine: AsyncEngine):
        self.async_sessionmaker = async_sessionmaker(async_engine, expire_on_commit=True)
        self.simulator_db = SimulatorORMExecutor(self.async_sessionmaker)
        self.hpc_database = HPCORMExecutor(self.async_sessionmaker)
        self.package_db = PackageORMExecutor(self.async_sessionmaker)
        self.events_db = EventsORMExecutor(self.async_sessionmaker)
        self.datasets_db = DatasetsORMExecutor(self.async_sessionmaker)

    @override
    def get_simulator_db(self) -> SimulatorDatabaseService:
        return self.simulator_db

    @override
    def get_hpc_db(self) -> HPCDatabaseService:
        return self.hpc_database

    @override
    def get_package_db(self) -> PackageDatabaseService:
        return self.package_db

    @override
    def get_events_db(self) -> EventsDatabaseService:
        return self.events_db

    @override
    def get_datasets_db(self) -> DatasetsDatabaseService:
        return self.datasets_db

    @override
    async def close(self) -> None:
        pass
