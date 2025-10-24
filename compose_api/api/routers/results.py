import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import FileResponse

from compose_api.common.gateway.models import Namespace, RouterConfig
from compose_api.common.gateway.utils import get_hpc_run_status
from compose_api.common.ssh.ssh_service import get_ssh_service
from compose_api.config import get_settings
from compose_api.dependencies import (
    get_data_service,
    get_database_service,
    get_required_database_service,
    get_simulation_service,
)
from compose_api.simulation.models import (
    HpcRun,
    JobType,
)

logger = logging.getLogger(__name__)

# -- app components -- #

config = RouterConfig(router=APIRouter(), prefix="/results", dependencies=[])


@config.router.get(
    path="/simulation/status",
    response_model=HpcRun,
    operation_id="get-simulation-status",
    tags=["Results"],
    dependencies=[Depends(get_database_service)],
    summary="Get the simulation status record by its ID",
)
async def get_simulation_status(simulation_id: int = Query(...)) -> HpcRun:
    db_service = get_database_service()
    if db_service is None:
        raise HTTPException(status_code=500, detail="Database service is not initialized")
    return await get_hpc_run_status(db_service=db_service, ref_id=simulation_id, job_type=JobType.SIMULATION)


# @config.router.get(
#     path="/simulation/run/events",
#     response_model=list[WorkerEvent],
#     operation_id="get-simulation-worker-events",
#     tags=["Simulations"],
#     dependencies=[Depends(get_simulation_service), Depends(get_database_service)],
#     summary="Get the worker events for a simulation by its ID",
# )
# async def get_simulation_worker_events(
#     simulation_id: int = Query(...),
#     num_events: int | None = Query(default=None),
#     prev_sequence_number: int | None = Query(default=None),
# ) -> list[WorkerEvent]:
#     sim_service = get_simulation_service()
#     if sim_service is None:
#         logger.error("Simulation service is not initialized")
#         raise HTTPException(status_code=500, detail="Simulation service is not initialized")
#     db_service = get_database_service()
#     if db_service is None:
#         logger.error("SSH service is not initialized")
#         raise HTTPException(status_code=500, detail="SSH service is not initialized")
#     try:
#         simulation_hpcrun: HpcRun | None = await db_service.get_hpcrun_by_ref(
#             ref_id=simulation_id, job_type=JobType.SIMULATION
#         )
#         if simulation_hpcrun:
#             worker_events = await db_service.list_worker_events(
#                 hpcrun_id=simulation_hpcrun.database_id,
#                 prev_sequence_number=prev_sequence_number,
#             )
#             return worker_events[:num_events] if num_events else worker_events
#         else:
#             return []
#     except Exception as e:
#         logger.exception(f"Error fetching simulation results for simulation id: {simulation_id}.")
#         raise HTTPException(status_code=500, detail=str(e)) from e


# @config.router.get(
#     path="/simulation/run/results/chunks",
#     response_class=ORJSONResponse,
#     operation_id="get-simulation-results",
#     tags=["Simulations"],
#     dependencies=[Depends(get_simulation_service), Depends(get_ssh_service)],
#     summary="Get simulation results in chunks",
# )
# async def get_result_chunks(
#     background_tasks: BackgroundTasks,
#     observable_names: RequestedObservables,
#     experiment_id: str = Query(default="experiment_96bb7a2_id_1_20250620-181422"),
#     database_id: int = Query(description="Database Id returned from /submit-simulation"),
#     git_commit_hash: str = Query(default="not-specified"),
# ) -> ORJSONResponse:
#     sim_service = get_simulation_service()
#     if sim_service is None:
#         logger.error("Simulation service is not initialized")
#         raise HTTPException(status_code=500, detail="Simulation service is not initialized")
#     ssh_service = get_ssh_service()
#     if ssh_service is None:
#         logger.error("SSH service is not initialized")
#         raise HTTPException(status_code=500, detail="SSH service is not initialized")
#     try:
#         service = DataServiceHpc()
#
#         local_dir, lazy_frame = await service.read_simulation_chunks(experiment_id, Namespace.TEST)
#         background_tasks.add_task(shutil.rmtree, local_dir)
#         selected_cols = observable_names.items if len(observable_names.items) else ["bulk", "^listeners__mass.*"]
#         data = (
#             lazy_frame.select(
#                 pl.col(selected_cols)  # regex pattern to match columns starting with this prefix
#             )
#             .collect()
#             .to_dict()
#         )
#         return ORJSONResponse(content=data)
#     except Exception as e:
#         logger.exception(f"Error fetching simulation results for id: {database_id}.")
#         raise HTTPException(status_code=500, detail=str(e)) from e


@config.router.get(
    path="/simulation/results/file",
    response_class=FileResponse,
    responses={
        200: {
            "content": {"application/octet-stream": {"schema": {"format": "binary"}}},
            "description": "Simulation result zip file",
        }
    },
    operation_id="get-simulation-results-file",
    tags=["Results"],
    dependencies=[Depends(get_simulation_service), Depends(get_ssh_service)],
    summary="Get simulation results as a zip file",
)
async def get_results(simulation_id: int = Query()) -> FileResponse:
    service = get_data_service()
    db_service = get_required_database_service()
    if service is None:
        logger.error("Data service is not initialized")
        raise HTTPException(status_code=500, detail="Data service is not initialized")
    try:
        experiment_id = await db_service.get_simulator_db().get_simulations_experiment_id(simulation_id=simulation_id)
        zip_path = await service.get_results_zip(experiment_id, Namespace(get_settings().namespace))
        file_response = FileResponse(
            path=zip_path, filename=f"{experiment_id}_results.zip", media_type="application/zip"
        )
        return file_response
    except Exception as e:
        # logger.exception(f"Error fetching simulation results for id: {database_id}.")
        raise HTTPException(status_code=500, detail=str(e)) from e


@config.router.get(
    path="/simulator/build/status",
    response_model=HpcRun,
    operation_id="get-simulator-build-status",
    tags=["Results"],
    dependencies=[Depends(get_database_service)],
    summary="Get the simulator build status record by its ID",
)
async def get_simulator_build_status(simulator_id: int = Query(...)) -> HpcRun:
    db_service = get_database_service()
    if db_service is None:
        raise HTTPException(status_code=500, detail="Database service is not initialized")
    return await get_hpc_run_status(db_service=db_service, ref_id=simulator_id, job_type=JobType.BUILD_CONTAINER)
