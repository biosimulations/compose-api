import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile

from compose_api.common.gateway.models import RouterConfig
from compose_api.common.gateway.utils import allow_list, get_file_from_uploaded_file
from compose_api.dependencies import (
    get_database_service,
    get_job_monitor,
    get_simulation_service,
)
from compose_api.simulation.handlers import (
    run_simulation,
)
from compose_api.simulation.models import (
    PBAllowList,
    SimulationExperiment,
)

logger = logging.getLogger(__name__)


# -- app components -- #

config = RouterConfig(router=APIRouter(), prefix="/simulation", dependencies=[])


@config.router.post(
    path="/run",
    operation_id="run-simulation",
    response_model=SimulationExperiment,
    tags=["Simulation"],
    dependencies=[Depends(get_simulation_service), Depends(get_database_service)],
    summary="Run a simulation",
)
async def submit_simulation(
    background_tasks: BackgroundTasks, uploaded_file: UploadFile, interval_time: float = 1.0
) -> SimulationExperiment:
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
    if interval_time < 0 or interval_time > 1000:
        raise HTTPException(status_code=400, detail="Invalid interval time, it has to be between 0 and 1000")

    simulation_request = await get_file_from_uploaded_file(uploaded_file=uploaded_file)
    simulation_request.end_time_point = interval_time

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


# @config.router.post(
#     path="/analyze",
#     response_class=PlainTextResponse,
#     description="Resulting container definition file",
#     operation_id="analyze-simulation-omex",
#     tags=["Simulation"],
#     summary="""Analyze a process bi-graph,
#     and determine the singularity definition file which would build an environment it can run in.""",
# )
# async def analyze_simulation(uploaded_file: UploadFile) -> str:
#     with tempfile.TemporaryDirectory() as tmp_dir:
#         contents = await uploaded_file.read()
#         uploaded_file_path = f"{tmp_dir}/{uploaded_file.filename}"
#         with open(uploaded_file_path, "wb") as fh:
#             fh.write(contents)
#         singularity_rep, experiment_dep = formulate_dockerfile_for_necessary_env(
#             ContainerizationProgramArguments(
#                 input_file_path=uploaded_file_path,
#                 working_directory=Path(tmp_dir),
#                 containerization_type=ContainerizationTypes.SINGLE,
#                 containerization_engine=ContainerizationEngine.APPTAINER,
#             )
#         )
#     return singularity_rep.representation


# @config.router.post(
#     path="/execute/sedml",
#     response_model=SimulationExperiment,
#     operation_id="execute-sedml",
#     tags=["Simulation"],
#     summary="Execute sedml",
# )
# async def execute_sedml(
#     uploaded_file: UploadFile, tool_suite: ToolSuites, background_tasks: BackgroundTasks
# ) -> SimulationExperiment:
#     omex_archive: Path = await get_file_from_uploaded_file(uploaded_file=uploaded_file)
#     with tempfile.TemporaryDirectory() as tmp_dir:
#         with zipfile.ZipFile(omex_archive, "r") as zip_ref:
#             zip_ref.extractall(path=tmp_dir)
#         for f in os.listdir(tmp_dir):
#             if f.rsplit(".", 1)[-1] == "sedml":
#                 rep = SimpleSedmlRepresentation.sed_processor(Path(f"{tmp_dir}/{f}"))
#                 pbif = SimpleSedmlCompiler.compile(sedml_repr=rep, tool_suite=tool_suite)
#                 return await run_pbif(
#                     templated_pbif=pbif,
#                     simulator_name=rep.solver_kisao,
#                     loaded_sbml=rep.sbml_path,
#                     background_tasks=background_tasks,
#                     use_interesting=False,
#                 )
#
#     raise HTTPException(status_code=422, detail="Couldn't find any SedML file.")


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
