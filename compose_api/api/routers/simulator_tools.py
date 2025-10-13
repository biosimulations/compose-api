import logging
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
    RegisteredSimulators,
    SimulationExperiment,
    SimulationRequest,
)

logger = logging.getLogger(__name__)


def get_server_url(dev: bool = True) -> ServerMode:
    return ServerMode.DEV if dev else ServerMode.PROD


# -- app components -- #

config = RouterConfig(router=APIRouter(), prefix="/tools", dependencies=[])


@config.router.get(
    path="/copasi",
    response_model=RegisteredSimulators,
    operation_id="use-copasi",
    tags=["Simulators"],
    dependencies=[Depends(get_database_service)],
    summary="Use the tool copasi.",
)
async def run_copasi(
    background_tasks: BackgroundTasks, sbml: UploadFile, start_time: float, duration: float, num_data_points: float
) -> SimulationExperiment:
    try:
        sim_service = get_required_simulation_service()
        db_service = get_required_database_service()
        job_monitor = get_required_job_monitor()
    except ValueError as e:
        logger.exception(msg="Failed to initialize Copasi run.", exc_info=e)
        raise HTTPException(status_code=500, detail=str(e))

    with open("copasi.jinja") as f:
        template = Template(f.read())
        render = template.render(start_time=start_time, duration=duration, num_data_points=num_data_points)

    with tempfile.TemporaryDirectory(delete=False) as tmp_dir:
        with zipfile.ZipFile(tmp_dir + "/input.omex", "w") as omex:
            loaded_sbml = await get_file_from_uploaded_file(uploaded_file=sbml)
            omex.writestr(data=render, zinfo_or_arcname="copasi.pbif")
            omex.write(loaded_sbml.name, arcname="interesting.sbml")
        if omex.filename is None:
            raise HTTPException(500, "Can't create omex file.")
        copasi_request = SimulationRequest(omex_archive=Path(omex.filename))

    try:
        return await run_simulation(
            simulation_request=copasi_request,
            database_service=db_service,
            simulation_service_slurm=sim_service,
            job_monitor=job_monitor,
            pb_allow_list=PBAllowList(allow_list=allow_list),
            background_tasks=background_tasks,
        )
    except Exception as e:
        logger.exception(msg="Failed to start Copasi run", exc_info=e)
        raise HTTPException(500)
