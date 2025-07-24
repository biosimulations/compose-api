import logging
import random
import string

from fastapi import BackgroundTasks, HTTPException

from biosim_api.common.gateway.models import RouterConfig
from biosim_api.dependencies import get_database_service
from biosim_api.simulation.database_service import DatabaseService
from biosim_api.simulation.hpc_utils import get_correlation_id, get_experiment_id
from biosim_api.simulation.models import (
    JobType,
    RegisteredSimulators,
    SimulationExperiment,
    SimulationRequest,
    SimulatorVersion,
)
from biosim_api.simulation.simulation_service import SimulationService

logger = logging.getLogger(__name__)

# -- roundtrip job handlers that both call the services and return the relative endpoint's DTO -- #


async def get_simulator_versions() -> RegisteredSimulators:
    sim_db_service = get_database_service()
    if sim_db_service is None:
        logger.error("Simulation database service is not initialized")
        raise HTTPException(status_code=500, detail="Simulation database service is not initialized")
    try:
        simulators = await sim_db_service.list_simulators()
        return RegisteredSimulators(versions=simulators)
    except Exception as e:
        logger.exception("Error getting list of simulation versions")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def run_simulation(
    simulator: SimulatorVersion,
    database_service: DatabaseService,
    simulation_service_slurm: SimulationService,
    router_config: RouterConfig,
    variant_config: dict[str, dict[str, int | float | str]] | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> SimulationExperiment:
    simulation_request = SimulationRequest(
        simulator=simulator,
        variant_config=variant_config or {"named_parameters": {"param1": 0.5, "param2": 0.5}},
    )
    simulation = await database_service.insert_simulation(sim_request=simulation_request)

    async def dispatch_job() -> None:
        random_string_7_hex = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
        correlation_id = get_correlation_id(simulation=simulation, random_string=random_string_7_hex)
        sim_slurmjobid = await simulation_service_slurm.submit_simulation_job(
            simulation=simulation,
            simulator_version=simulator,
            database_service=database_service,
            correlation_id=correlation_id,
        )
        _hpcrun = await database_service.insert_hpcrun(
            slurmjobid=sim_slurmjobid,
            job_type=JobType.SIMULATION,
            ref_id=simulation.database_id,
            correlation_id=correlation_id,
        )

    if background_tasks:
        background_tasks.add_task(dispatch_job)
    else:
        await dispatch_job()
    experiment_id = get_experiment_id(
        router_config=router_config, simulation=simulation, sim_request=simulation_request
    )

    return SimulationExperiment(experiment_id=experiment_id, simulation=simulation)
