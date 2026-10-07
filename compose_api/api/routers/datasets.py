"""The datasets runs advertise: list, describe, and read their content (docs/plan-observability.md O5, O6).

A dataset is readable by whoever may read its simulation (O7, O8); one the caller may not read is not found.
"""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import FileResponse

from compose_api.authorization import OptionalCaller, can_read, readable_clause
from compose_api.common.gateway.models import Namespace, RouterConfig
from compose_api.config import get_settings
from compose_api.db.services.datasets_db import DatasetQuery
from compose_api.dependencies import get_required_database_service
from compose_api.observability.datasets import Dataset, DatasetPage
from compose_api.simulation.hpc_utils import get_internal_experiment_dir

logger = logging.getLogger(__name__)

NOT_FOUND_RESPONSE = {"description": "The dataset does not exist, or the caller may not read it"}

config = RouterConfig(router=APIRouter(), prefix="/datasets", dependencies=[])


async def _readable_dataset(dataset_id: uuid.UUID, caller: OptionalCaller) -> Dataset:
    found = await get_required_database_service().get_datasets_db().get(dataset_id)
    if found is None or not can_read(caller, found[1]):
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found.")
    return found[0]


def resolve_content_path(experiment_dir: Path, relative: str) -> Path | None:
    """The file ``relative`` names inside ``experiment_dir``, or None if it resolves outside it (``..``, or a
    symlink that leaves the directory)."""
    root = experiment_dir.resolve()
    target = (root / relative).resolve()
    return target if target.is_relative_to(root) else None


@config.router.get(
    path="",
    response_model=DatasetPage,
    operation_id="list-datasets",
    responses={404: {"description": "The simulation does not exist, or the caller may not read it"}},
    tags=["Datasets"],
    summary="List the datasets runs advertised, newest simulations first",
)
async def list_datasets(
    caller: OptionalCaller,
    simulation_id: int | None = Query(default=None, description="Only this simulation's datasets"),
    kind: str | None = Query(default=None, description="Only this kind, e.g. results, table, figure, archive"),
    q: str | None = Query(default=None, description="Only datasets whose path or name contains this"),
    available: bool | None = Query(default=True, description="Only files that still exist (false: only missing)"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> DatasetPage:
    db = get_required_database_service()
    if simulation_id is not None:
        access = await db.get_simulator_db().get_simulations_access([simulation_id])
        if not access or not can_read(caller, access[0]):
            raise HTTPException(status_code=404, detail=f"Simulation with id {simulation_id} not found.")
    query = DatasetQuery(simulation_id=simulation_id, kind=kind, q=q, available=available, limit=limit, offset=offset)
    datasets, total = await db.get_datasets_db().page(query, readable=readable_clause(caller))
    following = offset + len(datasets)
    return DatasetPage(datasets=datasets, total=total, next_offset=following if following < total else None)


@config.router.get(
    path="/{dataset_id}",
    response_model=Dataset,
    operation_id="get-dataset",
    responses={404: NOT_FOUND_RESPONSE},
    tags=["Datasets"],
    summary="Describe one dataset",
)
async def get_dataset(dataset_id: uuid.UUID, caller: OptionalCaller) -> Dataset:
    return await _readable_dataset(dataset_id, caller)


@config.router.get(
    path="/{dataset_id}/content",
    response_class=FileResponse,
    operation_id="get-dataset-content",
    responses={
        200: {"content": {"application/octet-stream": {"schema": {"format": "binary"}}}, "description": "The file"},
        404: {"description": "The dataset does not exist, the caller may not read it, or its file is gone"},
    },
    tags=["Datasets"],
    summary="Read a dataset's file (supports HTTP Range requests)",
)
async def get_dataset_content(dataset_id: uuid.UUID, caller: OptionalCaller) -> FileResponse:
    dataset = await _readable_dataset(dataset_id, caller)
    db = get_required_database_service()
    experiment_id = await db.get_simulator_db().get_simulations_experiment_id(simulation_id=dataset.simulation_id)
    experiment_dir = get_internal_experiment_dir(experiment_id, Namespace(get_settings().namespace))
    path = resolve_content_path(experiment_dir, dataset.path)
    if path is None:
        logger.warning(f"Dataset {dataset_id} path {dataset.path!r} resolves outside its experiment directory")
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found.")
    if not path.is_file():
        if dataset.available:
            await db.get_datasets_db().set_available(dataset_id, False)
        raise HTTPException(status_code=404, detail=f"The file of dataset {dataset_id} is no longer available.")
    return FileResponse(path=path, media_type=dataset.media_type, filename=Path(dataset.path).name)
