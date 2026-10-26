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
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response

from compose_api.authentication import OptionalPrincipal, get_optional_principal
from compose_api.authorization import EnvironmentAdmin
from compose_api.common.gateway.models import RouterConfig
from compose_api.config import get_settings
from compose_api.dependencies import (
    get_database_service,
    get_required_database_service,
    get_required_job_monitor,
    get_required_simulation_service,
)
from compose_api.environments import compliance_runs, lifecycle, pixi
from compose_api.environments import service as environment_service
from compose_api.environments.contents import record_contents
from compose_api.environments.service import VersionRequestError
from compose_api.environments.versions import version_for
from compose_api.registry.environments import (
    CatalogEntry,
    EnvironmentSpec,
    EnvironmentSummary,
    InterfaceManifest,
    catalog_entries,
    load_environments,
    manifest_path,
    read_manifest,
    summarize,
    summarize_mash_up,
)
from compose_api.registry.headers import EnvironmentHeaders, environment_headers
from compose_api.registry.solvers import Solver, load_solvers
from compose_api.sedml.translator import TranslatorUnavailableError
from compose_api.simulation import builds, handlers
from compose_api.simulation.builds import ImageState, ImageStatus
from compose_api.simulation.models import (
    ComplianceReport,
    DefaultVersion,
    EnvironmentExport,
    EnvironmentVersion,
    EnvironmentVersionDetail,
    EnvironmentVersions,
    LockPreview,
    NewEnvironmentVersion,
    SimulatorVersion,
    VersionState,
)

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
    """The environments this deployment declares (environments.yaml), then the mash-ups the database holds
    (docs/plan-environment-composition.md, D7.9). Public: the same for every caller."""
    declared = [s for s in (summarize(spec) for spec in load_environments().environments) if s is not None]
    database_service = get_database_service()
    if database_service is None:
        return declared
    environments_db = database_service.get_environments_db()
    mash_ups = []
    for record in await environments_db.environments():
        if record.kind != "mash-up":
            continue
        default = await environments_db.get_default_detail(record.name)
        core = (default.spec or {}).get("core") if default is not None else None
        mash_ups.append(
            summarize_mash_up(record.name, record.entries or [], default.interfaces if default else None, core)
        )
    return [*declared, *mash_ups]


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


# --- environment versions (docs/plan-environment-versions.md, step 4) ----------------------------------------------

_NO_ENVIRONMENT: dict[int | str, dict[str, Any]] = {404: {"description": "No such environment, or no such version"}}
_ADMIN: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not signed in"},
    403: {"description": "Not an environment administrator, or environment administration is not configured"},
}


def _known_environment(name: str) -> EnvironmentSpec:
    spec = environment_service.environment_spec(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"no environment {name!r}")
    return spec


async def _readable_kind(name: str) -> str:
    """The kind of an environment whose versions may be read: one environments.yaml declares, or a mash-up the
    database holds (D7.9). 404 otherwise."""
    spec = environment_service.environment_spec(name)
    if spec is not None:
        return spec.kind
    records = await get_required_database_service().get_environments_db().environments()
    record = next((r for r in records if r.name == name and r.kind == "mash-up"), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no environment {name!r}")
    return record.kind


async def _version(name: str, number: int) -> EnvironmentVersionDetail:
    version = await get_required_database_service().get_environments_db().get_by_number(name, number)
    if version is None:
        raise HTTPException(status_code=404, detail=f"no version {name}@{number}")
    return version


@config.router.get(
    path="/environments/{name}/versions",
    response_model=EnvironmentVersions,
    operation_id="list-environment-versions",
    tags=["Registry"],
    summary="An environment's versions, newest first, and its default",
    responses=_NO_ENVIRONMENT,
)
async def list_environment_versions(name: str, principal: OptionalPrincipal) -> EnvironmentVersions:
    # public: the same for every caller
    kind = await _readable_kind(name)
    return await get_required_database_service().get_environments_db().describe(name, kind)


@config.router.get(
    path="/environments/{name}/versions/{number}",
    response_model=EnvironmentVersionDetail,
    operation_id="get-environment-version",
    tags=["Registry"],
    summary="One version of an environment: what it was made from, its lock, and what it installed and provides",
    responses=_NO_ENVIRONMENT,
)
async def get_environment_version(name: str, number: int, principal: OptionalPrincipal) -> EnvironmentVersionDetail:
    # public: the same for every caller
    await _readable_kind(name)
    version = await _version(name, number)
    pending = version.installed is None and version.interfaces is None
    if pending and version.state == VersionState.READY:  # built by a run, or before this service read images back
        database_service = get_required_database_service()
        if await record_contents(database_service, version):
            version = await _version(name, number)
    return version


@config.router.get(
    path="/environments/{name}/versions/{number}/export",
    response_model=EnvironmentExport,
    operation_id="export-environment-version",
    tags=["Registry"],
    summary="A version as files to recreate it locally: pixi files, uv files (without conda), or requirements",
    responses={
        **_NO_ENVIRONMENT,
        409: {"description": "The version has no lock in that format (prebuilt, older, or still resolving)"},
    },
)
async def export_environment_version(
    name: str,
    number: int,
    principal: OptionalPrincipal,
    format: Annotated[  # noqa: A002 the query parameter's name
        str | None, Query(description="pixi, uv (a composed version without conda) or requirements; pixi by default")
    ] = None,
) -> EnvironmentExport:
    # public: the same for every caller
    await _readable_kind(name)
    version = await _version(name, number)
    exports = await get_required_database_service().get_environments_db().get_exports(version.database_id)
    try:
        return environment_service.export(version, format, exports)
    except VersionRequestError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@config.router.get(
    path="/environments/{name}/versions/{number}/compliance",
    response_model=ComplianceReport,
    operation_id="get-environment-version-compliance",
    tags=["Registry"],
    summary="Where each entry of a version stands there (its cases' runs), and the components a generic check refuses",
    responses=_NO_ENVIRONMENT,
)
async def get_environment_version_compliance(name: str, number: int, principal: OptionalPrincipal) -> ComplianceReport:
    # public: the same for every caller; finished runs are evaluated as this is read
    await _readable_kind(name)
    database_service = get_required_database_service()
    version = await _version(name, number)
    await compliance_runs.refresh(database_service, version)
    return await compliance_runs.report(database_service, version)


@config.router.post(
    path="/environments/{name}/versions/{number}/compliance",
    response_model=ComplianceReport,
    status_code=202,
    operation_id="run-environment-version-compliance",
    tags=["Registry"],
    summary="Run a version's compliance cases again (its entries' cases, as committed now)",
    responses={**_NO_ENVIRONMENT, **_ADMIN, 409: {"description": "The version is not ready, or not composed"}},
)
async def run_environment_version_compliance(
    name: str, number: int, background_tasks: BackgroundTasks, caller: EnvironmentAdmin
) -> ComplianceReport:
    _known_environment(name)
    version = await _version(name, number)
    if version.state != VersionState.READY or version.runtime_contract != pixi.RUNTIME_CONTRACT:
        raise HTTPException(status_code=409, detail=f"{version.label} is not a ready composed version")
    detail_only = {"lock", "installed", "interfaces", "findings"}
    plain = EnvironmentVersion.model_validate(version.model_dump(exclude=detail_only))
    background_tasks.add_task(lifecycle.start_compliance, plain)
    logger.info(f"{version.label}: compliance run again for {caller.subject}")
    return await compliance_runs.report(get_required_database_service(), version)


@config.router.post(
    path="/environments/{name}/versions/preview",
    response_model=LockPreview,
    operation_id="preview-environment-version",
    tags=["Registry"],
    summary="Resolve a shared environment's spec without creating anything: the lock, and its changes from the default",
    responses={**_NO_ENVIRONMENT, **_ADMIN, 422: {"description": "The spec does not resolve, or is not a lock's"}},
)
async def preview_environment_version(
    name: str, request: NewEnvironmentVersion, caller: EnvironmentAdmin
) -> LockPreview:
    spec = _known_environment(name)
    try:
        return await environment_service.preview(get_required_database_service(), spec, request)
    except VersionRequestError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@config.router.post(
    path="/environments/{name}/versions",
    response_model=EnvironmentVersion,
    status_code=201,
    operation_id="create-environment-version",
    tags=["Registry"],
    summary="Make a new version: a shared environment's spec resolved at a date, or a prebuilt one's image by digest",
    responses={
        200: {"model": EnvironmentVersion, "description": "A version with this very definition exists: that one"},
        **_NO_ENVIRONMENT,
        **_ADMIN,
        422: {"description": "The request cannot make a version of this environment"},
    },
)
async def create_environment_version(
    name: str,
    request: NewEnvironmentVersion,
    background_tasks: BackgroundTasks,
    response: Response,
    caller: EnvironmentAdmin,
) -> EnvironmentVersion:
    """The new version is `building` until its image is built or pulled, then `ready` (or `failed`). It does not
    become the default: runs get it once an administrator makes it so (`PUT …/default`). A composed environment's
    version is `resolving` first, while its entries are locked together in a Job of their own; one that does not
    resolve is `failed`, with pixi's explanation in `failure` (docs/plan-environment-composition.md, step 4)."""
    database_service = get_required_database_service()
    declared = environment_service.environment_spec(name)
    spec = declared or await lifecycle.mash_up_spec(database_service, name)  # a mash-up's later versions (D7.7)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"no environment {name!r}")
    try:
        if environment_service.is_composed(spec):
            composed = await environment_service.create_composed(
                database_service, spec, request, caller.subject, bundled=declared is not None
            )
            background_tasks.add_task(lifecycle.resolve_and_build, composed)
            logger.info(f"{composed.label} created by {caller.subject}, resolving")
            return composed
        version, created = await environment_service.create(database_service, spec, request, caller.subject)
    except VersionRequestError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if not created:
        response.status_code = 200
    if (created or version.state in (VersionState.BUILDING, VersionState.FAILED)) and version.simulator_id is not None:
        simulator = await database_service.get_simulator_db().get_simulator(version.simulator_id)
        if simulator is not None:
            background_tasks.add_task(lifecycle.build_version, version, simulator)
            if version.state == VersionState.FAILED:
                await database_service.get_environments_db().set_state(version.database_id, VersionState.BUILDING)
                version = version.model_copy(update={"state": VersionState.BUILDING})
    logger.info(f"{version.label} {'created' if created else 'requested again'} by {caller.subject}")
    return version


@config.router.post(
    path="/environments/{name}/versions/{number}/inspect",
    response_model=EnvironmentVersion,
    status_code=202,
    operation_id="inspect-environment-version",
    tags=["Registry"],
    summary="Read again what a version's image installed and provides, in a Job that runs the image",
    responses={
        **_NO_ENVIRONMENT,
        **_ADMIN,
        409: {"description": "A shared version whose image is not built yet, or no Kubernetes to run the Job on"},
    },
)
async def inspect_environment_version(
    name: str, number: int, background_tasks: BackgroundTasks, caller: EnvironmentAdmin
) -> EnvironmentVersion:
    """Started in the background; `GET …/versions/{number}` shows the result. A prebuilt image is pulled and run; a
    shared one, already built, is read again as its build reads a new one (for images built before builds did)."""
    _known_environment(name)
    version = await _version(name, number)
    if version.image is None and version.state != VersionState.READY:
        raise HTTPException(status_code=409, detail=f"{version.label} is {version.state}: its build reads it back")
    if get_settings().build_backend != "k8s":
        raise HTTPException(status_code=409, detail="reading an image back needs the k8s build backend")
    plain = EnvironmentVersion.model_validate(version.model_dump(exclude={"lock", "installed", "interfaces"}))
    background_tasks.add_task(lifecycle.read_back, plain, reread=True)
    logger.info(f"{version.label} read back again, for {caller.subject}")
    return plain


@config.router.put(
    path="/environments/{name}/default",
    response_model=EnvironmentVersion,
    operation_id="set-environment-default",
    tags=["Registry"],
    summary="Make a ready version the one runs get when they name none",
    responses={**_NO_ENVIRONMENT, **_ADMIN, 409: {"description": "The version is not ready"}},
)
async def set_environment_default(name: str, request: DefaultVersion, caller: EnvironmentAdmin) -> EnvironmentVersion:
    _known_environment(name)
    version = await _version(name, request.number)
    if version.state != VersionState.READY:
        raise HTTPException(status_code=409, detail=f"{version.label} is {version.state}, not ready")
    await get_required_database_service().get_environments_db().set_default(name, version.database_id)
    logger.info(f"{version.label} made the default by {caller.subject}")
    return EnvironmentVersion.model_validate(version.model_dump(exclude={"lock", "installed", "interfaces"}))


@config.router.post(
    path="/environments/{name}/versions/{number}/retire",
    response_model=EnvironmentVersion,
    operation_id="retire-environment-version",
    tags=["Registry"],
    summary="Retire a version: it refuses new runs, and its images are kept for the runs that used it",
    responses={**_NO_ENVIRONMENT, **_ADMIN, 409: {"description": "It is the default; make another the default first"}},
)
async def retire_environment_version(name: str, number: int, caller: EnvironmentAdmin) -> EnvironmentVersion:
    _known_environment(name)
    version = await _version(name, number)
    environments_db = get_required_database_service().get_environments_db()
    default = await environments_db.get_default(name)
    if default is not None and default.database_id == version.database_id:
        raise HTTPException(status_code=409, detail=f"{version.label} is the default")
    await environments_db.set_state(version.database_id, VersionState.RETIRED)
    logger.info(f"{version.label} retired by {caller.subject}")
    retired = version.model_dump(exclude={"lock", "installed", "interfaces"}) | {"state": VersionState.RETIRED}
    return EnvironmentVersion.model_validate(retired)


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
