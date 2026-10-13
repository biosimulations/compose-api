"""The datasets runs advertise: list, describe, and read their content (docs/plan-observability.md O5, O6).

A dataset is readable by whoever may read its simulation (O7, O8); one the caller may not read is not found.
"""

import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import FileResponse

from compose_api.authentication import get_optional_principal
from compose_api.authorization import OptionalCaller, can_read, readable_clause
from compose_api.common.gateway.models import Namespace, RouterConfig
from compose_api.config import get_settings
from compose_api.db.services.datasets_db import DatasetQuery
from compose_api.dependencies import get_required_database_service
from compose_api.observability.datasets import Dataset, DatasetPage, infer_media_type
from compose_api.simulation.hpc_utils import get_internal_experiment_dir

logger = logging.getLogger(__name__)

NOT_FOUND_RESPONSE = {"description": "The dataset does not exist, or the caller may not read it"}

config = RouterConfig(router=APIRouter(), prefix="/datasets", dependencies=[Depends(get_optional_principal)])


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


def _unreadable(dataset_id: uuid.UUID, path: str) -> HTTPException:
    """A file the API's user may not read. Checked before responding: FileResponse opens the file only after sending
    the headers, so a PermissionError there broke the response mid-stream instead of failing it (simulation 4570)."""
    logger.error(f"Dataset {dataset_id}: {path!r} exists but is not readable by the API")
    return HTTPException(
        status_code=500, detail=f"Dataset {dataset_id}: the file exists but the server cannot read it."
    )


async def _dataset_path(dataset: Dataset) -> Path | None:
    """Where ``dataset`` lives on the mounted store, or None if its path resolves outside its experiment directory."""
    db = get_required_database_service()
    experiment_id = await db.get_simulator_db().get_simulations_experiment_id(simulation_id=dataset.simulation_id)
    experiment_dir = get_internal_experiment_dir(experiment_id, Namespace(get_settings().namespace))
    path = resolve_content_path(experiment_dir, dataset.path)
    if path is None:
        logger.warning(f"Dataset {dataset.id} path {dataset.path!r} resolves outside its experiment directory")
    return path


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
        409: {"description": "The dataset is a directory (a zarr store): read its files with get-dataset-file"},
    },
    tags=["Datasets"],
    summary="Read a dataset's file (supports HTTP Range requests)",
)
async def get_dataset_content(dataset_id: uuid.UUID, caller: OptionalCaller) -> FileResponse:
    dataset = await _readable_dataset(dataset_id, caller)
    db = get_required_database_service()
    path = await _dataset_path(dataset)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found.")
    if path.is_dir():
        raise HTTPException(
            status_code=409,
            detail=f"Dataset {dataset_id} is a directory; read its files at /datasets/{dataset_id}/files/<path>.",
        )
    if path.is_file() and not os.access(path, os.R_OK):
        raise _unreadable(dataset_id, dataset.path)
    if not path.is_file():
        if dataset.available:
            await db.get_datasets_db().set_available(dataset_id, False)
        raise HTTPException(status_code=404, detail=f"The file of dataset {dataset_id} is no longer available.")
    return FileResponse(path=path, media_type=dataset.media_type, filename=Path(dataset.path).name)


@config.router.get(
    path="/{dataset_id}/files/{subpath:path}",
    response_class=FileResponse,
    operation_id="get-dataset-file",
    responses={
        200: {"content": {"application/octet-stream": {"schema": {"format": "binary"}}}, "description": "The file"},
        404: {
            "description": "The dataset does not exist, the caller may not read it, it is not a directory, "
            "or it has no such file"
        },
    },
    tags=["Datasets"],
    summary="Read one file inside a directory dataset, e.g. a zarr store's metadata or chunk (supports HTTP Range)",
)
async def get_dataset_file(dataset_id: uuid.UUID, subpath: str, caller: OptionalCaller) -> FileResponse:
    """A directory dataset (a ``*.fenics`` results bundle, a ``*.zarr`` store) is read file by file, so a browser
    can fetch one chunk at a time with no server-side reduction (docs/plan-viewers.md F1). ``no-cache``: a live
    run rewrites the bundle's manifest after every row, so clients revalidate (the ETag makes that cheap)."""
    dataset = await _readable_dataset(dataset_id, caller)
    root = await _dataset_path(dataset)
    if root is None or not root.is_dir():
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} has no files.")
    target = resolve_content_path(root, subpath)
    if target is None or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} has no file {subpath!r}.")
    if not os.access(target, os.R_OK):
        raise _unreadable(dataset_id, f"{dataset.path}/{subpath}")
    return FileResponse(path=target, media_type=infer_media_type(subpath), headers={"Cache-Control": "no-cache"})
