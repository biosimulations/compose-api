import logging
from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from typing_extensions import override

from compose_api.db.hpc_db import HPCDatabase, HPCDatabaseSQL
from compose_api.db.simulators_db import SimulatorDB, SimulatorDBSQL

logger = logging.getLogger(__name__)


class DatabaseService(ABC):
    @abstractmethod
    def get_simulator_db(self) -> SimulatorDB:
        pass

    @abstractmethod
    def get_hpc_db(self) -> HPCDatabase:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class DatabaseServiceSQL(DatabaseService):
    async_sessionmaker: async_sessionmaker[AsyncSession]
    simulator_db: SimulatorDB
    hpc_database: HPCDatabase

    def __init__(self, async_engine: AsyncEngine):
        self.async_sessionmaker = async_sessionmaker(async_engine, expire_on_commit=True)
        self.simulator_db = SimulatorDBSQL(self.async_sessionmaker)
        self.hpc_database = HPCDatabaseSQL(self.async_sessionmaker)

    @override
    def get_simulator_db(self) -> SimulatorDB:
        return self.simulator_db

    @override
    def get_hpc_db(self) -> HPCDatabase:
        return self.hpc_database

    @override
    async def close(self) -> None:
        pass
