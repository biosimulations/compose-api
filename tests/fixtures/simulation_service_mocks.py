from typing import override

from compose_api.common.hpc.models import SlurmJob
from compose_api.simulation.database_service import DatabaseService
from compose_api.simulation.models import Simulation, SimulatorVersion
from compose_api.simulation.simulation_service import SimulationService


class ConcreteSimulationService(SimulationService):
    @override
    async def submit_simulation_job(
        self,
        simulation: Simulation,
        simulator_version: SimulatorVersion,
        database_service: DatabaseService,
        correlation_id: str,
    ) -> int:
        raise NotImplementedError

    @override
    async def get_slurm_job_status(self, slurmjobid: int) -> SlurmJob | None:
        raise NotImplementedError

    @override
    async def close(self) -> None:
        raise NotImplementedError
