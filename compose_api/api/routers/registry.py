"""The catalog of registry entries, the environments this service runs documents in, and the process interfaces each
one provides (docs/plan-sedml.md, "Concepts": the catalog is discovery and trust, an environment is execution).

The web app's composite editor and viewer check `.pblang` text against the manifest of the environment the document
runs in (docs/plan-authoring.md). The manifests are generated in CI inside each environment's image and ship with
this service (compose_api/registry/manifests/); see compose_api/registry/environments.py.
"""

import hashlib
import logging
import random
import string

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response

from compose_api.authentication import OptionalPrincipal, get_optional_principal
from compose_api.common.gateway.models import RouterConfig
from compose_api.dependencies import (
    get_required_database_service,
    get_required_job_monitor,
    get_required_simulation_service,
)
from compose_api.environments.versions import version_for
from compose_api.registry.environments import (
    CatalogEntry,
    EnvironmentSummary,
    InterfaceManifest,
    catalog_entries,
    load_environments,
    manifest_path,
    read_manifest,
    summarize,
)
from compose_api.registry.headers import EnvironmentHeaders, environment_headers
from compose_api.registry.solvers import Solver, load_solvers
from compose_api.sedml.translator import TranslatorUnavailableError
from compose_api.simulation import builds, handlers
from compose_api.simulation.builds import ImageState, ImageStatus
from compose_api.simulation.models import SimulatorVersion

logger = logging.getLogger(__name__)

config = RouterConfig(router=APIRouter(), prefix="/registry", dependencies=[Depends(get_optional_principal)])


@config.router.get(
    path="/environments",
    response_model=list[EnvironmentSummary],
    operation_id="list-environments",
    tags=["Registry"],
    summary="The environments documents run in, with what their interface manifests hold",
)
async def list_environments(principal: OptionalPrincipal) -> list[EnvironmentSummary]:
    # public: the same for every caller
    return [s for s in (summarize(spec) for spec in load_environments().environments) if s is not None]


@config.router.get(
    path="/environments/{name}/manifest",
    response_model=InterfaceManifest,
    operation_id="get-environment-manifest",
    tags=["Registry"],
    summary="An environment's interface manifest (pbg-interfaces/1), each component with its registry entry",
    responses={404: {"description": "No such environment here, or no manifest has been generated for it"}},
)
async def get_environment_manifest(
    name: str, request: Request, response: Response, principal: OptionalPrincipal
) -> InterfaceManifest | Response:
    # public: the same for every caller
    spec = next((e for e in load_environments().environments if e.name == name), None)
    if spec is None or summarize(spec) is None:
        raise HTTPException(status_code=404, detail=f"no environment {name!r}")
    path = manifest_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no interface manifest has been generated for {name!r}")
    etag = '"' + hashlib.sha256(path.read_bytes()).hexdigest()[:32] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    manifest = read_manifest(name)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"no interface manifest has been generated for {name!r}")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return manifest


@config.router.get(
    path="/environments/{name}/headers",
    response_model=EnvironmentHeaders,
    operation_id="get-environment-headers",
    tags=["Registry"],
    summary="An environment's interfaces as .pblang header files (one per module), and each class's declaration",
    responses={
        404: {"description": "No such environment here, or no manifest has been generated for it"},
        503: {"description": "process-bigraph-lang is not installed in this deployment"},
    },
)
async def get_environment_headers(name: str, principal: OptionalPrincipal) -> EnvironmentHeaders:
    # public: the same for every caller
    spec = next((e for e in load_environments().environments if e.name == name), None)
    if spec is None or summarize(spec) is None:
        raise HTTPException(status_code=404, detail=f"no environment {name!r}")
    try:
        headers = await environment_headers(name)
    except TranslatorUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if headers is None:
        raise HTTPException(status_code=404, detail=f"no interface manifest has been generated for {name!r}")
    return headers


@config.router.get(
    path="/entries",
    response_model=list[CatalogEntry],
    operation_id="list-registry-entries",
    tags=["Registry"],
    summary="The catalog: every registry entry with its curation level, pin and evidence, and the environments that "
    "provide its classes",
)
async def list_registry_entries(principal: OptionalPrincipal) -> list[CatalogEntry]:
    # public: the same for every caller
    return catalog_entries()


@config.router.get(
    path="/solvers",
    response_model=list[Solver],
    operation_id="list-solvers",
    tags=["Registry"],
    summary="The solvers SED-ML runs can use: each one's class, environment, KiSAO algorithms and what it returns",
)
async def list_solvers(principal: OptionalPrincipal) -> list[Solver]:
    # public: the same for every caller
    return list(load_solvers().solvers)


# --- environments' images: status, and builds on their own (docs/plan-environment-builds.md, phase 4) -------------


async def _environment_simulator(name: str) -> SimulatorVersion:
    spec = builds.find_environment(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"no environment {name!r}")
    # its default version's (docs/plan-environment-versions.md)
    _version, simulator = await version_for(get_required_database_service(), None if spec.kind == "shared" else name)
    return simulator


async def _simulator(simulator_id: int) -> SimulatorVersion:
    simulator = await get_required_database_service().get_simulator_db().get_simulator(simulator_id)
    if simulator is None:
        raise HTTPException(status_code=404, detail=f"no simulator {simulator_id}")
    return simulator


async def _build_in_background(simulator: SimulatorVersion) -> None:
    try:
        await handlers.ensure_image(
            simulator,
            database_service=get_required_database_service(),
            simulation_service_slurm=get_required_simulation_service(),
            job_monitor=get_required_job_monitor(),
            random_string="".join(random.choices(string.hexdigits, k=7)),  # noqa: S311 a name, not a secret
        )
    except Exception:
        logger.exception(f"The build of simulator {simulator.database_id}'s image failed")


async def _start_build(
    simulator: SimulatorVersion, environment: str | None, background_tasks: BackgroundTasks, response: Response
) -> ImageStatus:
    status = await builds.image_status(get_required_database_service(), simulator, environment)
    if status.state == ImageState.AVAILABLE:
        return status
    # pulled or built through the run path's own function: it joins a build that has not finished
    background_tasks.add_task(_build_in_background, simulator)
    response.status_code = 202
    return status.model_copy(update={"state": ImageState.BUILDING})


@config.router.get(
    path="/environments/{name}/images",
    response_model=ImageStatus,
    operation_id="get-environment-images",
    tags=["Registry"],
    summary="Whether an environment's current image is built, with its image records and newest build run",
    responses={404: {"description": "No such environment here"}},
)
async def get_environment_images(name: str, principal: OptionalPrincipal) -> ImageStatus:
    # public: the same for every caller
    simulator = await _environment_simulator(name)
    return await builds.image_status(get_required_database_service(), simulator, name)


@config.router.post(
    path="/environments/{name}/build",
    response_model=ImageStatus,
    operation_id="build-environment",
    tags=["Registry"],
    summary="Make an environment's current image available: 200 if it is, 202 once its pull or build has started",
    responses={
        202: {"model": ImageStatus, "description": "Its pull or build has started (or was already under way)"},
        404: {"description": "No such environment here"},
    },
)
async def build_environment(
    name: str, background_tasks: BackgroundTasks, response: Response, principal: OptionalPrincipal
) -> ImageStatus:
    # anyone who may submit a run may cause this build: a run of the environment would start it
    return await _start_build(await _environment_simulator(name), name, background_tasks, response)


@config.router.get(
    path="/simulators/{simulator_id}/images",
    response_model=ImageStatus,
    operation_id="get-simulator-images",
    tags=["Registry"],
    summary="Whether a simulator's image is built, with its image records and newest build run",
    responses={404: {"description": "No such simulator"}},
)
async def get_simulator_images(simulator_id: int, principal: OptionalPrincipal) -> ImageStatus:
    # public: the same for every caller
    return await builds.image_status(get_required_database_service(), await _simulator(simulator_id))


@config.router.post(
    path="/simulators/{simulator_id}/build",
    response_model=ImageStatus,
    operation_id="build-simulator",
    tags=["Registry"],
    summary="Make a simulator's image available: 200 if it is, 202 once its pull or build has started",
    responses={
        202: {"model": ImageStatus, "description": "Its pull or build has started (or was already under way)"},
        404: {"description": "No such simulator"},
    },
)
async def build_simulator(
    simulator_id: int, background_tasks: BackgroundTasks, response: Response, principal: OptionalPrincipal
) -> ImageStatus:
    return await _start_build(await _simulator(simulator_id), None, background_tasks, response)
