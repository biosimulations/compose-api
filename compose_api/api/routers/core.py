import logging
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile
from starlette.responses import FileResponse, PlainTextResponse

from compose_api.btools.bsander.bsandr_utils.input_types import (
    ContainerizationEngine,
    ContainerizationTypes,
    ProgramArguments,
)
from compose_api.btools.bsander.execution import execute_bsander
from compose_api.btools.sedml_compiler.sedml_representation_compiler import SimpleSedmlCompiler, ToolSuites
from compose_api.btools.sedml_processor import SimpleSedmlRepresentation
from compose_api.common.gateway.models import Namespace, RouterConfig, ServerMode
from compose_api.common.gateway.utils import allow_list, get_file_from_uploaded_file, get_hpc_run_status
from compose_api.common.ssh.ssh_service import get_ssh_service
from compose_api.config import get_settings
from compose_api.dependencies import (
    get_data_service,
    get_database_service,
    get_job_monitor,
    get_required_database_service,
    get_simulation_service,
)
from compose_api.simulation.handlers import (
    run_pbif,
    run_simulation,
)
from compose_api.simulation.models import (
    HpcRun,
    JobType,
    PBAllowList,
    SimulationExperiment,
    SimulationRequest,
)

logger = logging.getLogger(__name__)


def get_server_url(dev: bool = True) -> ServerMode:
    return ServerMode.DEV if dev else ServerMode.PROD


# -- app components -- #

config = RouterConfig(router=APIRouter(), prefix="/core", dependencies=[])


# @config.router.get(
#     path="/simulator/versions",
#     response_model=RegisteredSimulators,
#     operation_id="get-simulator-versions",
#     tags=["Simulators"],
#     dependencies=[Depends(get_database_service), Depends(get_postgres_engine)],
#     summary="get the list of available simulator versions",
# )
# async def get_simulator_versions() -> RegisteredSimulators:
#     sim_db_service = get_database_service()
#     if sim_db_service is None:
#         logger.error("Simulation database service is not initialized")
#         raise HTTPException(status_code=500, detail="Simulation database service is not initialized")
#     try:
#         simulators = await sim_db_service.list_simulators()
#         return RegisteredSimulators(versions=simulators)
#     except Exception as e:
#         logger.exception("Error getting list of simulation versions")
#         raise HTTPException(status_code=500, detail=str(e)) from e


@config.router.post(
    path="/simulation/run",
    operation_id="run-simulation",
    response_model=SimulationExperiment,
    tags=["Execute"],
    dependencies=[Depends(get_simulation_service), Depends(get_database_service)],
    summary="Run a simulation",
)
async def submit_simulation(background_tasks: BackgroundTasks, uploaded_file: UploadFile) -> SimulationExperiment:
    sim_service = get_simulation_service()
    if sim_service is None:
        logger.error("Simulation service is not initialized")
        raise HTTPException(status_code=500, detail="Simulation service is not initialized")
    db_service = get_database_service()
    if db_service is None:
        logger.error("Database service is not initialized")
        raise HTTPException(status_code=500, detail="Database service is not initialized")
    job_monitor = get_job_monitor()
    if job_monitor is None:
        logger.error("Job Monitor service is not initialized")
        raise HTTPException(status_code=500, detail="Job Monitor service is not initialized")

    # TODO ################################################################################
    # !!! Input validation for Omex file, preferably converting it to an internal type !!!#
    #######################################################################################
    logger.warning("NO VALIDATION YET")
    # Tmp file for future implementation

    up_file = await get_file_from_uploaded_file(uploaded_file=uploaded_file)
    simulation_request = SimulationRequest(omex_archive=up_file)

    try:
        return await run_simulation(
            simulation_request=simulation_request,
            database_service=db_service,
            simulation_service_slurm=sim_service,
            background_tasks=background_tasks,
            job_monitor=job_monitor,
            # TODO: Put/Get actual allow list
            pb_allow_list=PBAllowList(allow_list=allow_list),
        )
    except Exception as e:
        logger.exception("Error running simulation")
        raise HTTPException(status_code=500, detail=str(e)) from e


# @config.router.get(
#     path="/simulation/run/versions",
#     response_model=list[Simulation],
#     operation_id="get-simulation-versions",
#     tags=["Simulations"],
#     summary="Get list of simulations",
# )
# async def get_simulation_versions() -> list[Simulation]:
#     db_service = get_database_service()
#     if db_service is None:
#         logger.error("Simulation database service is not initialized")
#         raise HTTPException(status_code=500, detail="Simulation database service is not initialized")
#
#     try:
#         simulations: list[Simulation] = await db_service.list_simulations()
#         return simulations
#     except Exception as e:
#         logger.exception("Error getting simulations")
#         raise HTTPException(status_code=500, detail=str(e)) from e


@config.router.post(
    path="/simulation/analyze",
    response_class=PlainTextResponse,
    description="Resulting container definition file",
    operation_id="analyze-simulation-omex",
    tags=["Execute"],
    summary="""Analyze a process bi-graph,
    and determine the singularity definition file which would build an environment it can run in.""",
)
async def analyze_simulation(uploaded_file: UploadFile) -> str:
    with tempfile.TemporaryDirectory() as tmp_dir:
        contents = await uploaded_file.read()
        uploaded_file_path = f"{tmp_dir}/{uploaded_file.filename}"
        with open(uploaded_file_path, "wb") as fh:
            fh.write(contents)
        singularity_rep, experiment_dep = execute_bsander(
            ProgramArguments(
                input_file_path=uploaded_file_path,
                output_dir=tmp_dir,
                containerization_type=ContainerizationTypes.SINGLE,
                containerization_engine=ContainerizationEngine.APPTAINER,
                passlist_entries=allow_list,
            )
        )
    return singularity_rep.representation


@config.router.get(
    path="/simulation/run/status",
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
    path="/simulation/run/results/file",
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


@config.router.post(
    path="/simulation/execute/sedml",
    response_model=SimulationExperiment,
    operation_id="execute-sedml",
    tags=["Execute"],
    summary="Execute sedml",
)
async def execute_sedml(
    uploaded_file: UploadFile, tool_suite: ToolSuites, background_tasks: BackgroundTasks
) -> SimulationExperiment:
    omex_archive: Path = await get_file_from_uploaded_file(uploaded_file=uploaded_file)
    with tempfile.TemporaryDirectory() as tmp_dir:
        with zipfile.ZipFile(omex_archive, "r") as zip_ref:
            zip_ref.extractall(path=tmp_dir)
        for f in os.listdir(tmp_dir):
            if f.rsplit(".", 1)[-1] == "sedml":
                rep = SimpleSedmlRepresentation.sed_processor(Path(f"{tmp_dir}/{f}"))
                pbif = SimpleSedmlCompiler.compile(sedml_repr=rep, tool_suite=tool_suite)
                return await run_pbif(
                    templated_pbif=pbif,
                    simulator_name=rep.solver_kisao,
                    loaded_sbml=rep.sbml_path,
                    background_tasks=background_tasks,
                    use_interesting=False,
                )

    raise HTTPException(status_code=422, detail="Couldn't find any SedML file.")
