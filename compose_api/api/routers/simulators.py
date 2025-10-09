import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from compose_api.common.gateway.models import RouterConfig, ServerMode
from compose_api.common.gateway.utils import get_hpc_run_status
from compose_api.dependencies import (
    get_database_service,
)
from compose_api.simulation.handlers import (
    get_simulator_versions,
)
from compose_api.simulation.models import (
    HpcRun,
    JobType,
    RegisteredSimulators,
)

logger = logging.getLogger(__name__)


def get_server_url(dev: bool = True) -> ServerMode:
    return ServerMode.DEV if dev else ServerMode.PROD


# -- app components -- #

config = RouterConfig(router=APIRouter(), prefix="/core", dependencies=[])


@config.router.get(
    path="/simulator/build/status",
    response_model=HpcRun,
    operation_id="get-simulator-build-status",
    tags=["Simulators"],
    dependencies=[Depends(get_database_service)],
    summary="Get the simulator build status record by its ID",
)
async def get_simulator_build_status(simulator_id: int = Query(...)) -> HpcRun:
    db_service = get_database_service()
    if db_service is None:
        raise HTTPException(status_code=500, detail="Database service is not initialized")
    return await get_hpc_run_status(db_service=db_service, ref_id=simulator_id, job_type=JobType.BUILD_CONTAINER)


@config.router.get(
    path="/simulator/list",
    response_model=RegisteredSimulators,
    operation_id="get-simulator-list",
    tags=["Simulators"],
    dependencies=[Depends(get_database_service)],
    summary="Get the list of simulators",
)
async def get_simulator_list() -> RegisteredSimulators:
    return await get_simulator_versions()


# @config.router.get(
#     path="/simulator/process/list",
#     response_model=RegisteredSimulators,
#     operation_id="get-processes-list",
#     tags=["Simulators"],
#     dependencies=[Depends(get_database_service)],
#     summary="Get the list of processes.",
# )
# async def get_process_list() -> RegisteredProcesses:
#     pass
