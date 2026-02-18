import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from jinja2 import Template

from compose_api.common.gateway.models import RouterConfig, ServerMode
from compose_api.common.gateway.utils import get_file_from_uploaded_file
from compose_api.dependencies import (
    get_database_service,
)
from compose_api.simulation.handlers import (
    run_curated_pbif,
)
from compose_api.simulation.models import (
    SimulationExperiment,
    SimulationFileType,
)

logger = logging.getLogger(__name__)


def get_server_url(dev: bool = True) -> ServerMode:
    return ServerMode.DEV if dev else ServerMode.PROD


# -- app components -- #

config = RouterConfig(router=APIRouter(), prefix="/curated", dependencies=[])


@config.router.post(
    path="/copasi",
    response_model=SimulationExperiment,
    operation_id="run-copasi",
    tags=["Curated"],
    dependencies=[Depends(get_database_service)],
    summary="Use the tool copasi.",
)
async def run_copasi(
    background_tasks: BackgroundTasks, sbml: UploadFile, start_time: float, duration: float, num_data_points: float
) -> SimulationExperiment:
    with open(os.path.dirname(__file__) + "/templates/copasi.jinja") as f:
        template = Template(f.read())
        render = template.render(start_time=start_time, duration=duration, num_data_points=num_data_points)
    request = await get_file_from_uploaded_file(sbml)
    if request.simulation_file_type is not SimulationFileType.SBML:
        raise HTTPException(status_code=400, detail="Expected a SBML file.")
    return await run_curated_pbif(
        templated_pbif=render,
        simulator_name="Copasi",
        loaded_sbml=request.request_file_path,
        background_tasks=background_tasks,
        use_interesting=True,
    )


@config.router.post(
    path="/tellurium",
    response_model=SimulationExperiment,
    operation_id="run-tellurium",
    tags=["Curated"],
    dependencies=[Depends(get_database_service)],
    summary="Use the tool tellurium.",
)
async def run_tellurium(
    background_tasks: BackgroundTasks, sbml: UploadFile, start_time: float, end_time: float, num_data_points: float
) -> SimulationExperiment:
    with open(os.path.dirname(__file__) + "/templates/tellurium.jinja") as f:
        template = Template(f.read())
        render = template.render(start_time=start_time, end_time=end_time, num_data_points=num_data_points)
    request = await get_file_from_uploaded_file(sbml)
    if request.simulation_file_type is not SimulationFileType.SBML:
        raise HTTPException(status_code=400, detail="Expected a SBML file.")
    return await run_curated_pbif(
        templated_pbif=render,
        simulator_name="Tellurium",
        loaded_sbml=request.request_file_path,
        background_tasks=background_tasks,
    )
