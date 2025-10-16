import logging
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from jinja2 import Template

from compose_api.common.gateway.models import RouterConfig, ServerMode
from compose_api.common.gateway.utils import allow_list, get_file_from_uploaded_file
from compose_api.dependencies import (
    get_database_service,
    get_required_database_service,
    get_required_job_monitor,
    get_required_simulation_service,
)
from compose_api.simulation.handlers import (
    run_simulation,
)
from compose_api.simulation.models import (
    PBAllowList,
    SimulationExperiment,
    SimulationRequest,
)

logger = logging.getLogger(__name__)


def get_server_url(dev: bool = True) -> ServerMode:
    return ServerMode.DEV if dev else ServerMode.PROD


# -- app components -- #

config = RouterConfig(router=APIRouter(), prefix="/tools", dependencies=[])


@config.router.post(
    path="/copasi",
    response_model=SimulationExperiment,
    operation_id="run-copasi",
    tags=["Simulators"],
    dependencies=[Depends(get_database_service)],
    summary="Use the tool copasi.",
)
async def run_copasi(
    background_tasks: BackgroundTasks, sbml: UploadFile, start_time: float, duration: float, num_data_points: float
) -> SimulationExperiment:
    with open(os.path.dirname(__file__) + "/copasi.jinja") as f:
        template = Template(f.read())
        render = template.render(start_time=start_time, duration=duration, num_data_points=num_data_points)

    return await _run_simulator_in_pbif(
        templated_pbif=render, simulator_name="Copasi", sbml_file=sbml, background_tasks=background_tasks
    )


@config.router.post(
    path="/tellurium",
    response_model=SimulationExperiment,
    operation_id="run-tellurium",
    tags=["Simulators"],
    dependencies=[Depends(get_database_service)],
    summary="Use the tool tellurium.",
)
async def run_tellurium(
    background_tasks: BackgroundTasks, sbml: UploadFile, start_time: float, end_time: float, num_data_points: float
) -> SimulationExperiment:
    with open(os.path.dirname(__file__) + "/tellurium.jinja") as f:
        template = Template(f.read())
        render = template.render(start_time=start_time, duration=end_time, num_data_points=num_data_points)
    return await _run_simulator_in_pbif(
        templated_pbif=render, simulator_name="Tellurium", sbml_file=sbml, background_tasks=background_tasks
    )


async def _run_simulator_in_pbif(
    templated_pbif: str, simulator_name: str, sbml_file: UploadFile, background_tasks: BackgroundTasks
) -> SimulationExperiment:
    # Create OMEX with all necessary files
    with tempfile.TemporaryDirectory(delete=False) as tmp_dir:
        with zipfile.ZipFile(tmp_dir + "/input.omex", "w") as omex:
            loaded_sbml = await get_file_from_uploaded_file(uploaded_file=sbml_file)
            omex.writestr(data=templated_pbif, zinfo_or_arcname=f"{simulator_name}.pbif")
            omex.write(loaded_sbml.absolute(), arcname="interesting.sbml")
        if omex.filename is None:
            raise HTTPException(500, "Can't create omex file.")
        simulator_request = SimulationRequest(omex_archive=Path(omex.filename))

    try:
        sim_service = get_required_simulation_service()
        db_service = get_required_database_service()
        job_monitor = get_required_job_monitor()
    except ValueError as e:
        logger.exception(msg=f"Failed to initialize {simulator_name} run.", exc_info=e)
        raise HTTPException(status_code=500, detail=str(e))

    try:
        return await run_simulation(
            simulation_request=simulator_request,
            database_service=db_service,
            simulation_service_slurm=sim_service,
            job_monitor=job_monitor,
            pb_allow_list=PBAllowList(allow_list=allow_list),
            background_tasks=background_tasks,
        )
    except Exception as e:
        logger.exception(msg=f"Failed to start {simulator_name} run", exc_info=e)
        raise HTTPException(500)
