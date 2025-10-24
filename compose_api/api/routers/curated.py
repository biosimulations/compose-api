import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
from jinja2 import Template

from compose_api.common.gateway.models import RouterConfig, ServerMode
from compose_api.common.gateway.utils import get_file_from_uploaded_file
from compose_api.dependencies import (
    get_database_service,
)
from compose_api.simulation.handlers import (
    run_pbif,
)
from compose_api.simulation.models import (
    SimulationExperiment,
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
    loaded_sbml = await get_file_from_uploaded_file(sbml)
    return await run_pbif(
        templated_pbif=render, simulator_name="Copasi", loaded_sbml=loaded_sbml, background_tasks=background_tasks
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
    loaded_sbml = await get_file_from_uploaded_file(sbml)
    return await run_pbif(
        templated_pbif=render, simulator_name="Tellurium", loaded_sbml=loaded_sbml, background_tasks=background_tasks
    )
