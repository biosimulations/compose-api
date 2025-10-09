import logging

from fastapi import HTTPException

from compose_api.db.database_service import DatabaseService
from compose_api.simulation.models import HpcRun, JobType

logger = logging.getLogger(__name__)


def format_version(major: int) -> str:
    return f"v{major}"


def root_prefix(major: int) -> str:
    return f"/api/{format_version(major)}"


async def get_simulation_hpcrun(simulation_id: int, db_service: DatabaseService) -> HpcRun | None:
    hpcrun = await db_service.get_hpc_db().get_hpcrun_by_ref(ref_id=simulation_id, job_type=JobType.SIMULATION)
    return hpcrun


def format_marimo_appname(appname: str) -> str:
    """Capitalizes and separates appnames(module names) if needed."""
    if "_" in appname:
        return appname.replace("_", " ").title()
    else:
        return appname.replace(appname[0], appname[0].upper())


async def get_hpc_run_status(db_service: DatabaseService, ref_id: int, job_type: JobType) -> HpcRun:
    if db_service is None:
        logger.error("SSH service is not initialized")
        raise HTTPException(status_code=500, detail="SSH service is not initialized")
    try:
        simulation_hpcrun: HpcRun | None = await db_service.get_hpc_db().get_hpcrun_by_ref(
            ref_id=ref_id, job_type=job_type
        )
    except Exception as e:
        logger.exception(f"Error fetching status for {job_type} id: {ref_id}.")
        raise HTTPException(status_code=500, detail=str(e)) from e

    if simulation_hpcrun is None:
        raise HTTPException(status_code=404, detail=f"{job_type} with id {ref_id} not found.")
    return simulation_hpcrun


allow_list = [
    "pypi::git+https://github.com/biosimulators/bspil-basico.git@initial_work",
    "pypi::cobra",
    "pypi::tellurium",
    "pypi::copasi-basico",
    "pypi::smoldyn",
    "pypi::numpy",
    "pypi::matplotlib",
    "pypi::scipy",
]
