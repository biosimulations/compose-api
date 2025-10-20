import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from compose_api.common.gateway.models import RouterConfig, ServerMode
from compose_api.common.gateway.utils import get_hpc_run_status
from compose_api.dependencies import (
    get_database_service,
    get_required_database_service,
)
from compose_api.simulation.handlers import (
    get_simulator_versions,
)
from compose_api.simulation.models import (
    BiGraphComputeType,
    BiGraphProcess,
    BiGraphStep,
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


@config.router.get(
    path="/processes/list",
    response_model=list[BiGraphProcess],
    operation_id="get-processes-list",
    tags=["Simulators"],
    dependencies=[Depends(get_database_service)],
    summary="Get the list of processes",
)
async def get_processes_list() -> list[BiGraphProcess]:
    res: list[BiGraphProcess] = (
        await get_required_database_service().get_package_db().list_all_computes(BiGraphComputeType.PROCESS)
    )
    return res


@config.router.get(
    path="/steps/list",
    response_model=list[BiGraphStep],
    operation_id="get-steps-list",
    tags=["Simulators"],
    dependencies=[Depends(get_database_service)],
    summary="Get the list of processes",
)
async def get_steps_list() -> list[BiGraphStep]:
    res: list[BiGraphStep] = (
        await get_required_database_service().get_package_db().list_all_computes(BiGraphComputeType.STEP)
    )
    return res


# @config.router.post(
#     path="/simulator/register/bspil",
#     response_model=list[RegisteredPackage],
#     operation_id="regsiter-bspil",
#     tags=["Simulators"],
#     dependencies=[Depends(get_database_service)],
#     summary="Register the package that contains Copasi and Tellurium.",
# )
# async def register_bspil() -> list[RegisteredPackage]:
#     with open(os.path.dirname(__file__) + "/copasi.jinja") as f:
#         dependencies, _ = determine_dependencies(f.read(), whitelist_entries=allow_list)
#         dependencies = await get_required_database_service().get_package_db(
#         ).dependencies_not_in_database(dependencies)
#     package_outlines = introspect_package(dependencies)
#     registered_packages = []
#     for p in package_outlines:
#         registered_packages.append(await get_required_database_service().get_package_db().insert_package(p))
#     return registered_packages


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
