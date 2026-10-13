"""Where SED-ML archives come from besides uploads: EBI BioModels and biosimulations.org (docs/plan-sedml.md, phase 4).

Read-only views of each source, its archive (cached by id and upstream revision, compose_api/sedml/sources.py), and
shortcuts that run it like `/sedml/run`. A biosimulations.org project's original results join its comparisons as a
reference."""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from compose_api.authentication import OptionalPrincipal, get_optional_principal
from compose_api.common.gateway.models import RouterConfig
from compose_api.sedml import sources
from compose_api.sedml.models import SedmlRunResult, Tolerances
from compose_api.sedml.sources import BiomodelHit, BiomodelInfo, ProjectInfo

config = RouterConfig(router=APIRouter(), prefix="/sources", dependencies=[Depends(get_optional_principal)])

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "No such model or project upstream"}}
UNAVAILABLE: dict[int | str, dict[str, Any]] = {502: {"description": "The upstream service did not answer as expected"}}
Solvers = Annotated[list[str] | None, Query(description="Solvers to run (registry/solvers.yaml); all when omitted")]
Tasks = Annotated[list[str] | None, Query(description="Only these SED-ML task ids; all when omitted")]
Tags = Annotated[list[str] | None, Query(description="Tags for every run")]


def _upstream(e: Exception) -> HTTPException:
    if isinstance(e, sources.SourceNotFoundError):
        return HTTPException(status_code=404, detail=f"not found upstream: {e}")
    return HTTPException(status_code=502, detail=f"upstream unavailable: {e}")


@config.router.get(
    "/biomodels/search", response_model=list[BiomodelHit], operation_id="search-biomodels", tags=["Sources"],
    summary="Search EBI BioModels (manually curated models unless curated=false)", responses=UNAVAILABLE,
)  # fmt: skip
async def search_biomodels(
    principal: OptionalPrincipal,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    curated: bool = True,
) -> list[BiomodelHit]:
    try:
        return await sources.search_biomodels(q, limit, curated)
    except (sources.SourceNotFoundError, sources.SourceUnavailableError) as e:
        raise _upstream(e) from e


@config.router.get(
    "/biomodels/{model_id}", response_model=BiomodelInfo, operation_id="get-biomodel", tags=["Sources"],
    summary="One BioModels entry: name, curation status, latest revision", responses={**NOT_FOUND, **UNAVAILABLE},
)  # fmt: skip
async def get_biomodel(model_id: str, principal: OptionalPrincipal) -> BiomodelInfo:
    try:
        return await sources.biomodel(model_id)
    except (sources.SourceNotFoundError, sources.SourceUnavailableError) as e:
        raise _upstream(e) from e


@config.router.get(
    "/biomodels/{model_id}/omex", response_class=FileResponse, operation_id="get-biomodel-omex", tags=["Sources"],
    summary="The entry's COMBINE archive (its latest revision)", responses={**NOT_FOUND, **UNAVAILABLE},
)  # fmt: skip
async def get_biomodel_omex(model_id: str, principal: OptionalPrincipal) -> FileResponse:
    try:
        path = await sources.biomodel_archive(model_id)
    except (sources.SourceNotFoundError, sources.SourceUnavailableError) as e:
        raise _upstream(e) from e
    return FileResponse(path, media_type="application/zip", filename=f"{model_id}.omex")


@config.router.post(
    "/biomodels/{model_id}/run", response_model=SedmlRunResult, operation_id="run-biomodel", tags=["Sources"],
    summary="Run a BioModels entry's SED-ML on several solvers (as /sedml/run)", responses={**NOT_FOUND, **UNAVAILABLE},
)  # fmt: skip
async def run_biomodel(
    model_id: str, background_tasks: BackgroundTasks, principal: OptionalPrincipal,
    solvers: Solvers = None, task: Tasks = None, tags: Tags = None, description: str | None = None,
) -> SedmlRunResult:  # fmt: skip
    from compose_api.api.routers.sedml import run_archive

    try:
        path = await sources.biomodel_archive(model_id)
    except (sources.SourceNotFoundError, sources.SourceUnavailableError) as e:
        raise _upstream(e) from e
    return await run_archive(
        path, f"biomodels:{model_id}", solvers, task, tags, description, Tolerances(), background_tasks
    )


@config.router.get(
    "/biosimulations/projects", response_model=list[ProjectInfo], operation_id="search-biosimulations-projects",
    tags=["Sources"], summary="biosimulations.org projects whose id contains q", responses=UNAVAILABLE,
)  # fmt: skip
async def search_projects(
    principal: OptionalPrincipal,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[ProjectInfo]:
    try:
        return await sources.search_projects(q, limit)
    except (sources.SourceNotFoundError, sources.SourceUnavailableError) as e:
        raise _upstream(e) from e


@config.router.get(
    "/biosimulations/{project_id}", response_model=ProjectInfo, operation_id="get-biosimulations-project",
    tags=["Sources"], summary="One biosimulations.org project: its run and the simulator that ran it",
    responses={**NOT_FOUND, **UNAVAILABLE},
)  # fmt: skip
async def get_project(project_id: str, principal: OptionalPrincipal) -> ProjectInfo:
    try:
        return await sources.project(project_id)
    except (sources.SourceNotFoundError, sources.SourceUnavailableError) as e:
        raise _upstream(e) from e


@config.router.get(
    "/biosimulations/{project_id}/omex", response_class=FileResponse, operation_id="get-biosimulations-omex",
    tags=["Sources"], summary="The project's archive", responses={**NOT_FOUND, **UNAVAILABLE},
)  # fmt: skip
async def get_project_omex(project_id: str, principal: OptionalPrincipal) -> FileResponse:
    try:
        path = await sources.project_archive(project_id)
    except (sources.SourceNotFoundError, sources.SourceUnavailableError) as e:
        raise _upstream(e) from e
    return FileResponse(path, media_type="application/zip", filename=f"{project_id}.omex")


@config.router.get(
    "/biosimulations/{project_id}/reference", operation_id="get-biosimulations-reference", tags=["Sources"],
    summary="The project's original results: each report as {label: values}", responses={**NOT_FOUND, **UNAVAILABLE},
)  # fmt: skip
async def get_project_reference(project_id: str, principal: OptionalPrincipal) -> dict[str, dict[str, list[float]]]:
    try:
        return await sources.project_reference(project_id)
    except (sources.SourceNotFoundError, sources.SourceUnavailableError) as e:
        raise _upstream(e) from e


@config.router.post(
    "/biosimulations/{project_id}/run", response_model=SedmlRunResult, operation_id="run-biosimulations-project",
    tags=["Sources"], summary="Run a project's SED-ML on several solvers, its original results as the reference",
    responses={**NOT_FOUND, **UNAVAILABLE},
)  # fmt: skip
async def run_project(
    project_id: str, background_tasks: BackgroundTasks, principal: OptionalPrincipal,
    solvers: Solvers = None, task: Tasks = None, tags: Tags = None, description: str | None = None,
) -> SedmlRunResult:  # fmt: skip
    from compose_api.api.routers.sedml import run_archive

    try:
        path = await sources.project_archive(project_id)
        info = await sources.project(project_id)
        reference = await sources.project_reference(project_id)
    except (sources.SourceNotFoundError, sources.SourceUnavailableError) as e:
        raise _upstream(e) from e
    return await run_archive(
        path, f"biosimulations:{project_id}", solvers, task, tags, description, Tolerances(), background_tasks,
        references={f"biosimulations:{info.simulator or info.run}": reference} if reference else None,
    )  # fmt: skip
