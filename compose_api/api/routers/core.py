import logging
import shutil
import tempfile
from pathlib import Path

import polars as pl
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse, ORJSONResponse

from compose_api.common.gateway.models import Namespace, RouterConfig, ServerMode
from compose_api.common.ssh.ssh_service import get_ssh_service
from compose_api.dependencies import (
    get_database_service,
    get_postgres_engine,
    get_simulation_service,
)
from compose_api.simulation.data_service import DataServiceHpc
from compose_api.simulation.handlers import (
    run_simulation,
)
from compose_api.simulation.models import (
    HpcRun,
    JobType,
    RegisteredSimulators,
    RequestedObservables,
    Simulation,
    SimulationExperiment,
    SimulationRequest,
    WorkerEvent,
)

logger = logging.getLogger(__name__)


def get_server_url(dev: bool = True) -> ServerMode:
    return ServerMode.DEV if dev else ServerMode.PROD


# -- app components -- #

config = RouterConfig(router=APIRouter(), prefix="/core", dependencies=[])


@config.router.get(
    path="/simulator/versions",
    response_model=RegisteredSimulators,
    operation_id="get-simulator-versions",
    tags=["Simulators"],
    dependencies=[Depends(get_database_service), Depends(get_postgres_engine)],
    summary="get the list of available simulator versions",
)
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


@config.router.post(
    path="/simulation/run",
    operation_id="run-simulation",
    response_model=SimulationExperiment,
    tags=["Simulations"],
    dependencies=[Depends(get_simulation_service), Depends(get_database_service)],
    summary="Run a simulation",
)
async def submit_simulation(background_tasks: BackgroundTasks, sim_request: SimulationRequest) -> SimulationExperiment:
    sim_service = get_simulation_service()
    if sim_service is None:
        logger.error("Simulation service is not initialized")
        raise HTTPException(status_code=500, detail="Simulation service is not initialized")
    db_service = get_database_service()
    if db_service is None:
        logger.error("Database service is not initialized")
        raise HTTPException(status_code=500, detail="Database service is not initialized")

    try:
        return await run_simulation(
            simulator=sim_request.simulator,
            database_service=db_service,
            simulation_service_slurm=sim_service,
            router_config=config,
            background_tasks=background_tasks,
        )
    except Exception as e:
        logger.exception("Error running simulation")
        raise HTTPException(status_code=500, detail=str(e)) from e


@config.router.get(
    path="/simulation/run/versions",
    response_model=list[Simulation],
    operation_id="get-simulation-versions",
    tags=["Simulations"],
    summary="Get list of simulations",
)
async def get_simulation_versions() -> list[Simulation]:
    db_service = get_database_service()
    if db_service is None:
        logger.error("Simulation database service is not initialized")
        raise HTTPException(status_code=500, detail="Simulation database service is not initialized")

    try:
        simulations: list[Simulation] = await db_service.list_simulations()
        return simulations
    except Exception as e:
        logger.exception("Error getting simulations")
        raise HTTPException(status_code=500, detail=str(e)) from e


@config.router.get(
    path="/simulation/run/status",
    response_model=HpcRun,
    operation_id="get-simulation-status",
    tags=["Simulations"],
    dependencies=[Depends(get_database_service)],
    summary="Get the simulation status record by its ID",
)
async def get_simulation_status(
    simulation_id: int = Query(...), num_events: int | None = Query(default=None)
) -> HpcRun:
    db_service = get_database_service()
    if db_service is None:
        logger.error("SSH service is not initialized")
        raise HTTPException(status_code=500, detail="SSH service is not initialized")
    try:
        simulation_hpcrun: HpcRun | None = await db_service.get_hpcrun_by_ref(
            ref_id=simulation_id, job_type=JobType.SIMULATION
        )
    except Exception as e:
        logger.exception(f"Error fetching simulation results for simulation id: {simulation_id}.")
        raise HTTPException(status_code=500, detail=str(e)) from e

    if simulation_hpcrun is None:
        raise HTTPException(status_code=404, detail=f"Simulation with id {simulation_id} not found.")
    return simulation_hpcrun


@config.router.get(
    path="/simulation/run/events",
    response_model=list[WorkerEvent],
    operation_id="get-simulation-worker-events",
    tags=["Simulations"],
    dependencies=[Depends(get_simulation_service), Depends(get_database_service)],
    summary="Get the worker events for a simulation by its ID",
)
async def get_simulation_worker_events(
    simulation_id: int = Query(...),
    num_events: int | None = Query(default=None),
    prev_sequence_number: int | None = Query(default=None),
) -> list[WorkerEvent]:
    sim_service = get_simulation_service()
    if sim_service is None:
        logger.error("Simulation service is not initialized")
        raise HTTPException(status_code=500, detail="Simulation service is not initialized")
    db_service = get_database_service()
    if db_service is None:
        logger.error("SSH service is not initialized")
        raise HTTPException(status_code=500, detail="SSH service is not initialized")
    try:
        simulation_hpcrun: HpcRun | None = await db_service.get_hpcrun_by_ref(
            ref_id=simulation_id, job_type=JobType.SIMULATION
        )
        if simulation_hpcrun:
            worker_events = await db_service.list_worker_events(
                hpcrun_id=simulation_hpcrun.database_id,
                prev_sequence_number=prev_sequence_number,
            )
            return worker_events[:num_events] if num_events else worker_events
        else:
            return []
    except Exception as e:
        logger.exception(f"Error fetching simulation results for simulation id: {simulation_id}.")
        raise HTTPException(status_code=500, detail=str(e)) from e


@config.router.get(
    path="/simulation/run/results/chunks",
    response_class=ORJSONResponse,
    operation_id="get-simulation-results",
    tags=["Simulations"],
    dependencies=[Depends(get_simulation_service), Depends(get_ssh_service)],
    summary="Get simulation results in chunks",
)
async def get_result_chunks(
    background_tasks: BackgroundTasks,
    observable_names: RequestedObservables,
    experiment_id: str = Query(default="experiment_96bb7a2_id_1_20250620-181422"),
    database_id: int = Query(description="Database Id returned from /submit-simulation"),
    git_commit_hash: str = Query(default="not-specified"),
) -> ORJSONResponse:
    sim_service = get_simulation_service()
    if sim_service is None:
        logger.error("Simulation service is not initialized")
        raise HTTPException(status_code=500, detail="Simulation service is not initialized")
    ssh_service = get_ssh_service()
    if ssh_service is None:
        logger.error("SSH service is not initialized")
        raise HTTPException(status_code=500, detail="SSH service is not initialized")
    try:
        service = DataServiceHpc()

        local_dir, lazy_frame = await service.read_simulation_chunks(experiment_id, Namespace.TEST)
        background_tasks.add_task(shutil.rmtree, local_dir)
        selected_cols = observable_names.items if len(observable_names.items) else ["bulk", "^listeners__mass.*"]
        data = (
            lazy_frame.select(
                pl.col(selected_cols)  # regex pattern to match columns starting with this prefix
            )
            .collect()
            .to_dict()
        )
        return ORJSONResponse(content=data)
    except Exception as e:
        logger.exception(f"Error fetching simulation results for id: {database_id}.")
        raise HTTPException(status_code=500, detail=str(e)) from e


@config.router.get(
    path="/simulation/run/results/file",
    response_class=FileResponse,
    operation_id="get-simulation-results-file",
    tags=["Simulations"],
    dependencies=[Depends(get_simulation_service), Depends(get_ssh_service)],
    summary="Get simulation results as a zip file",
)
async def get_results(
    background_tasks: BackgroundTasks,
    experiment_id: str = Query(default="experiment_96bb7a2_id_1_20250620-181422"),
    database_id: int = Query(default_factory=int, description="Database Id of simulation"),
) -> FileResponse:
    try:
        service = DataServiceHpc()
        local_dir = await service.read_chunks(experiment_id, Namespace.TEST)
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            zip_path = Path(tmp.name)
            shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=local_dir)
            background_tasks.add_task(shutil.rmtree, local_dir)
        return FileResponse(path=zip_path, filename=f"{experiment_id}_chunks.zip", media_type="application/zip")
    except Exception as e:
        logger.exception(f"Error fetching simulation results for id: {database_id}.")
        raise HTTPException(status_code=500, detail=str(e)) from e
