import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile

from compose_api.api.errors import Rejection, SubmissionError, error
from compose_api.authentication import (
    AuthenticatedPrincipal,
    OptionalPrincipal,
    describe_caller,
    get_optional_principal,
)
from compose_api.authorization import RequestedVisibility, may_run_long, ownership_at_submit, roles_of
from compose_api.common.gateway.models import RouterConfig
from compose_api.common.gateway.utils import get_simulation_request_from_uploaded_file, wrap_document_in_omex
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseService
from compose_api.dependencies import (
    get_database_service,
    get_job_monitor,
    get_required_database_service,
    get_simulation_service,
)
from compose_api.environments import lifecycle
from compose_api.environments.admission import standing_for
from compose_api.environments.manifests import interfaces_of
from compose_api.environments.versions import VersionUnavailableError, chosen_version, environment_of, prebuilt_images
from compose_api.registry.access import entry_roles, environment_roles, hidden_environments, recorded_roles, usable
from compose_api.registry.environments import EnvironmentSpec, load_environments, members_of, offered
from compose_api.registry.manifest import SERVICE_BUNDLE, Manifest, load_manifest
from compose_api.registry.resolver import covering_environment, needed_entries
from compose_api.registry.validation import (
    REFUSED,
    AddressPolicy,
    AddressViolation,
    SubmissionRejectedError,
    class_targets,
    find_violations,
    unprovided_violations,
    unregistered_violations,
    validate_submission,
)
from compose_api.simulation.handlers import (
    run_simulation,
)
from compose_api.simulation.labels import (
    MAX_DESCRIPTION,
    MAX_TAGS,
    LabelError,
    clean_description,
    clean_tags,
    labels,
)
from compose_api.simulation.models import (
    SimulationExperiment,
    SimulationFileType,
)

logger = logging.getLogger(__name__)


# -- app components -- #

config = RouterConfig(router=APIRouter(), prefix="/simulation", dependencies=[Depends(get_optional_principal)])

REJECTED_RESPONSE = error(
    "The submission cannot run. For a problem with the request itself (empty file, unsupported type, "
    "interval out of range) `detail` is a string. For a problem with its contents (unreadable archive, or processes "
    "the registry does not allow) `detail` is an object with a `message` and a `violations` list naming each address.",
    SubmissionError,
)


async def _named_environment(
    environment: str | None, simulator: str | None, hidden: frozenset[str]
) -> tuple[str | None, str | None]:
    """The prebuilt simulator a request's `environment` and `simulator` name (None: the shared environment, or none
    named), and the undeclared composed environment it names (a mash-up), if it does. `environment` names any
    environment this deployment offers or the database holds; `simulator` is the older name for a prebuilt one, kept
    for a release (docs/plan-environment-composition.md, D7.1). A prebuilt one is offered when it has a default
    version (D8.3). A 400 when they disagree or the name is unknown; one ``hidden`` from the caller (a private
    repository's, registry/access.py) is unknown to them."""
    images = {
        name: image for name, image in (await prebuilt_images(get_database_service())).items() if name not in hidden
    }
    if simulator is not None and simulator not in images:
        offered_here = ", ".join(sorted(images)) or "none"
        raise HTTPException(
            status_code=400, detail=f"unknown simulator {simulator!r}; this deployment offers: {offered_here}"
        )
    if environment is None:
        return simulator, None
    spec = next((e for e in load_environments().environments if e.name == environment and e.name not in hidden), None)
    if spec is None and environment not in hidden and await _is_mash_up(environment):
        if simulator is not None:
            raise HTTPException(status_code=400, detail=f"`environment={environment}` is a mash-up, not `{simulator}`.")
        return None, environment
    if spec is None or not offered(spec, images):
        raise HTTPException(status_code=400, detail=f"No environment {environment!r} is offered here.")
    named = spec.name if spec.kind == "prebuilt" else None
    if simulator is not None and simulator != named:
        raise HTTPException(
            status_code=400, detail=f"`environment={environment}` and `simulator={simulator}` disagree."
        )
    return named, None


async def _is_mash_up(name: str) -> bool:
    database_service = get_database_service()
    if database_service is None:
        return False
    records = await database_service.get_environments_db().environments()
    return any(r.name == name and r.kind == "mash-up" for r in records)


@dataclass(frozen=True)
class _Inferred:
    """Where a run that names no environment goes: a prebuilt simulator, a mash-up (and the version of it made for
    this run), or neither (the shared environment)."""

    simulator: str | None = None
    mash_up: str | None = None
    version: int | None = None


async def _advertised(database_service: DatabaseService | None, environment: str) -> frozenset[str] | None:
    """The classes (`<module>.<Class>`) an environment's default version advertises, as read back from its image; None
    when nothing has been read back from it yet."""
    interfaces = await interfaces_of(database_service, environment)
    if interfaces is None:
        return None
    components = interfaces.get("components") or []
    return frozenset(f"{c.get('module')}.{c.get('name')}" for c in components if isinstance(c, dict))


def _refused(path: Path, violations: list[AddressViolation]) -> HTTPException:
    """The 400 for a run refused before an environment is chosen; its upload is removed, as validation's refusal is."""
    path.unlink(missing_ok=True)
    return HTTPException(status_code=400, detail=Rejection(message=REFUSED, violations=violations).model_dump())


async def _covering(
    path: Path,
    file_type: SimulationFileType,
    targets: list[str],
    needed: set[str],
    database_service: DatabaseService | None,
) -> EnvironmentSpec | None:
    """The environment that holds the run's packages and whose image advertises every class it names (its interface
    manifest, read back from the image); one with nothing read back yet (a version still building) is judged by its
    packages, as before. One that holds the packages but lacks a class (a class the package does not have at that pin,
    or one that failed to import there) is a 400 naming it under `enforce`, rather than a run sent to fail at import.
    One that also holds a private repository the run does not need is never chosen: its run would need that role to
    be read (registry/access.py)."""
    manifest = load_manifest()
    allowed = entry_roles(needed, manifest)
    recorded = await recorded_roles(database_service)

    def within(spec: EnvironmentSpec) -> bool:
        """Whether the environment needs no role the run's own entries do not (registry/access.py)."""
        return environment_roles(spec, manifest) | recorded.get(spec.name, frozenset()) <= allowed

    images = await prebuilt_images(database_service)
    mash_ups = [
        spec
        for spec in (await lifecycle.mash_up_specs(database_service) if database_service is not None else [])
        if within(spec)
    ]
    environments = load_environments()
    on_offer = [s for s in environments.environments if s.kind == "shared" or offered(s, images)] + list(mash_ups)
    advertised = {
        spec.name: await _advertised(database_service, spec.name)
        for spec in on_offer
        if needed <= members_of(spec, manifest)
    }
    classes = set(targets)

    def provides(spec: EnvironmentSpec) -> bool:
        found = advertised.get(spec.name)
        return found is None or classes <= found

    def on_offer_here(spec: EnvironmentSpec) -> bool:
        return offered(spec, images) and within(spec)

    def covering_by(check: Callable[[EnvironmentSpec], bool]) -> EnvironmentSpec | None:
        return covering_environment(
            needed, manifest, environments, offered=on_offer_here, mash_ups=mash_ups, provides=check
        )

    covering = covering_by(provides)
    if covering is not None:
        return covering
    by_packages = covering_by(lambda spec: True)
    if by_packages is None or AddressPolicy(get_settings().address_policy) != AddressPolicy.ENFORCE:
        return by_packages  # warn: as before, the environment holding the packages
    provided = advertised.get(by_packages.name) or frozenset()
    raise _refused(path, unprovided_violations(path, file_type, manifest, provided, by_packages.name))


async def _inferred(
    path: Path,
    file_type: SimulationFileType,
    principal: AuthenticatedPrincipal | None,
    background_tasks: BackgroundTasks,
    manifest: Manifest | None = None,
) -> _Inferred:
    """The environment a run that names none uses, from the classes its documents name (registry/resolver.py): the
    shared environment for everything it covers, as before, then the smallest declared one, then a mash-up that
    covers them. Nothing covering entries that can be composed, the mash-up of exactly those is made for the run
    (step 7b, D7.4): only for a signed-in caller (D7.5); its build follows in the background. Anything else (an
    unreadable submission, a class under no entry, an entry that cannot be composed) goes to the shared environment,
    whose validation says why it cannot run. ``manifest`` is the one the caller may use (registry/access.py): a
    private repository's class is unregistered to a caller without its role, and never joins a mash-up made for them."""
    manifest = manifest or load_manifest()
    try:
        # qualified as validation qualifies them, so a core short name (`local:RAMEmitter`) is not "unregistered"
        targets = [manifest.qualified(t) for t in class_targets(path, file_type)]
        violations = find_violations(path, file_type, manifest)
        unregistered = unregistered_violations(path, file_type, manifest)
    except SubmissionRejectedError:
        return _Inferred()
    refused = any(v.always_rejected for v in violations)
    # A class under no entry is refused before an environment is chosen: an inferred prebuilt image is validated without
    # the registry lookup, so it would reach the image and fail at import there instead of being refused by name. The
    # rejection names those classes (and any unsafe address), not the rest: naming those would point at an environment.
    if unregistered:
        if AddressPolicy(get_settings().address_policy) != AddressPolicy.ENFORCE:
            return _Inferred()  # warn: the shared environment's validation logs them and the run goes ahead there
        raise _refused(path, [v for v in violations if v.always_rejected] + unregistered)
    needed = needed_entries(targets, manifest)
    database_service = get_database_service()
    covering = await _covering(path, file_type, targets, needed, database_service)
    if covering is not None:
        if covering.kind == "prebuilt":
            return _Inferred(simulator=covering.name)
        return _Inferred(mash_up=covering.name) if covering.kind == "mash-up" else _Inferred()
    # nothing is made for a run validation will refuse anyway: an unsafe address
    if not needed or refused or database_service is None or lifecycle.composable(needed, manifest):
        return _Inferred()
    if principal is None:
        raise HTTPException(
            status_code=401,
            detail=f"no environment provides all of {', '.join(sorted(needed))}; sign in to have one made for this run",
        )
    try:
        version, simulator = await lifecycle.mash_up_for(database_service, needed, principal.subject)
    except lifecycle.MashUpError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from e
    if simulator is not None:
        background_tasks.add_task(lifecycle.build_and_export, version, simulator)
    return _Inferred(mash_up=version.environment, version=version.number)


def time_limit_minutes(interval_time: float) -> int | None:
    """The SLURM time limit for a run of this interval: None (the usual limit) up to the anonymous interval cap; past
    it, the usual limit scaled by the interval, up to the longest the deployment allows."""
    settings = get_settings()
    if interval_time <= settings.max_interval_time:
        return None
    scaled = math.ceil(settings.slurm_time_limit_minutes * interval_time / settings.max_interval_time)
    return min(settings.slurm_max_time_limit_minutes, scaled)


def _checked_options(
    principal: AuthenticatedPrincipal | None, interval_time: float, tags: list[str] | None, description: str | None
) -> tuple[list[str], str | None, int | None]:
    """The request's own parameters, checked before its file is read: a 400 for any the service does not accept.
    Also the run's SLURM time limit, which only a long run (authorization.may_run_long) raises."""
    try:
        run_tags, run_description = clean_tags(tags), clean_description(description)
    except LabelError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    settings = get_settings()
    long_runs = may_run_long(principal)
    cap = settings.max_long_run_interval_time if long_runs else settings.max_interval_time
    if not 0 <= interval_time <= cap:  # NaN fails every comparison, so it is refused too
        longer = ""
        if not long_runs and settings.max_long_run_interval_time > cap:
            role = settings.long_run_role.strip()
            who = f"with the {role} role" if role else "signed in"
            longer = f"; up to {settings.max_long_run_interval_time:.15g} {who}"
        raise HTTPException(
            status_code=400, detail=f"Invalid interval time, it has to be between 0 and {cap:.15g}{longer}"
        )
    return run_tags, run_description, time_limit_minutes(interval_time)


@config.router.post(
    path="/run",
    operation_id="run-simulation",
    response_model=SimulationExperiment,
    tags=["Simulation"],
    dependencies=[Depends(get_simulation_service), Depends(get_database_service)],
    summary="Run a simulation",
    responses={400: REJECTED_RESPONSE},
)
async def submit_simulation(
    background_tasks: BackgroundTasks,
    uploaded_file: UploadFile,
    principal: OptionalPrincipal,
    interval_time: float = 1.0,
    batch_submission: bool = False,
    simulator: str | None = None,
    tags: Annotated[
        list[str] | None,
        Query(description=f"Tags to find the run by later; at most {MAX_TAGS}, each up to 64 characters"),
    ] = None,
    description: Annotated[
        str | None, Query(description=f"What the run is for; up to {MAX_DESCRIPTION} characters")
    ] = None,
    environment: Annotated[
        str | None,
        Query(
            description="The environment to run in, by name (GET /registry/environments lists them). Omitted with"
            " `simulator` and `environment_version`: inferred from the classes the documents name"
        ),
    ] = None,
    environment_version: Annotated[
        int | None,
        Query(
            ge=1,
            description="The version of the environment to run in (registry_env@3 is 3, or of the prebuilt simulator"
            " named); omitted: its default. GET /registry/environments/{name}/versions lists them",
        ),
    ] = None,
    visibility: RequestedVisibility = None,
) -> SimulationExperiment:
    """`environment` names the environment to run in; `simulator` is the older way to name a prebuilt one (an
    owner-published image registered as a version of its environment). With neither, and no
    `environment_version`, the environment is inferred from the classes the documents name
    (docs/plan-environment-composition.md, step 7a): the shared environment for everything it provides, as before;
    otherwise the smallest offered environment that provides them all.
    `environment_version` picks a version of that environment (docs/plan-environment-versions.md); the run is labelled
    `environment_version=<environment>@<number>` either way.

    The run is labelled `source=upload` and `environment=<simulator or registry_env>`; `tags` and `description` are
    stored with it as given (compose_api/simulation/labels.py) and filter `GET /simulations`."""
    logger.info("Simulation submission from %s", describe_caller(principal))
    run_tags, run_description, time_limit = _checked_options(principal, interval_time, tags, description)
    ownership = ownership_at_submit(principal, visibility)
    # what this caller may use: without a private repository's entries and environments unless they hold its role
    roles = roles_of(principal)
    manifest = usable(load_manifest(), roles)
    simulator, composed = await _named_environment(
        environment, simulator, await hidden_environments(get_database_service(), roles)
    )
    named = environment is not None or simulator is not None or environment_version is not None
    if environment_version is not None:
        try:
            await chosen_version(
                get_required_database_service(), composed or environment_of(simulator), environment_version
            )
        except VersionUnavailableError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    simulation_request = await get_simulation_request_from_uploaded_file(
        uploaded_file=uploaded_file, batch_submission=batch_submission
    )
    if not named:  # D7.1: the environment inferred from the documents, a mash-up made for it if need be (7b)
        inferred = await _inferred(
            simulation_request.request_file_path,
            simulation_request.simulation_file_type,
            principal,
            background_tasks,
            manifest,
        )
        simulator, composed, environment_version = inferred.simulator, inferred.mash_up, inferred.version
    simulation_request.end_time_point = interval_time
    simulation_request.time_limit_minutes = time_limit
    simulation_request.simulator = simulator
    simulation_request.environment_version = environment_version
    simulation_request.environment = composed
    simulation_request.labels = labels(source="upload", environment=composed or simulator or SERVICE_BUNDLE)
    simulation_request.tags = run_tags
    simulation_request.description = run_description
    # Checked before anything is recorded or submitted: the container resolves addresses itself, and will import
    # whatever module it is told to, so this is the only point a submission is checked. A prebuilt simulator's
    # image brings its own processes, which this registry does not describe, so its classes are not looked up (the
    # administrator vouched for the image by registering it as a version); the unsafe forms, `local:!`
    # and any other protocol, are refused for it all the same.
    # what the version it will run in certifies (docs/plan-environment-composition.md, step 5c): a component refused
    # there, or an entry whose compliance cases failed there, is refused before the manifest's level is consulted
    database_service = get_database_service()  # none: no version to consult, so the manifest alone decides
    standing = (
        await standing_for(database_service, composed or environment_of(None), environment_version)
        if simulator is None and database_service is not None
        else None
    )
    try:
        validate_submission(
            simulation_request.request_file_path,
            simulation_request.simulation_file_type,
            AddressPolicy(get_settings().address_policy),
            registry=simulator is None,
            standing=standing,
            environment=composed or environment_of(simulator),
            manifest=manifest,
        )
    except SubmissionRejectedError as e:
        simulation_request.request_file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=Rejection(message=e.message, violations=e.violations).model_dump(),
        ) from e

    simulation_request = wrap_document_in_omex(simulation_request)

    sim_service = get_simulation_service()
    if sim_service is None:
        logger.error("Simulation service is not initialized")
        raise HTTPException(status_code=500, detail="Simulation service is not initialized")
    db_service = get_database_service()
    if db_service is None:
        logger.error("Database service is not initialized")
        raise HTTPException(status_code=500, detail="Database service is not initialized")
    job_monitor = get_job_monitor()
    if job_monitor is None:
        logger.error("Job Monitor service is not initialized")
        raise HTTPException(status_code=500, detail="Job Monitor service is not initialized")

    try:
        return await run_simulation(
            simulation_request=simulation_request,
            database_service=db_service,
            simulation_service_slurm=sim_service,
            background_tasks=background_tasks,
            job_monitor=job_monitor,
            ownership=ownership,  # docs/plan-favorites-and-studies.md, F1, F3
            requested_by=principal.subject if principal is not None else None,  # the queue's fair-share seam
        )
    except Exception as e:
        logger.exception("Error running simulation")
        raise HTTPException(status_code=500, detail=str(e)) from e


# @config.router.post(
#     path="/analyze",
#     response_class=PlainTextResponse,
#     description="Resulting container definition file",
#     operation_id="analyze-simulation-omex",
#     tags=["Simulation"],
#     summary="""Analyze a process bi-graph,
#     and determine the singularity definition file which would build an environment it can run in.""",
# )
# async def analyze_simulation(uploaded_file: UploadFile) -> str:
#     with tempfile.TemporaryDirectory() as tmp_dir:
#         contents = await uploaded_file.read()
#         uploaded_file_path = f"{tmp_dir}/{uploaded_file.filename}"
#         with open(uploaded_file_path, "wb") as fh:
#             fh.write(contents)
#         singularity_rep, experiment_dep = formulate_dockerfile_for_necessary_env(
#             ContainerizationProgramArguments(
#                 input_file_path=uploaded_file_path,
#                 working_directory=Path(tmp_dir),
#                 containerization_type=ContainerizationTypes.SINGLE,
#                 containerization_engine=ContainerizationEngine.APPTAINER,
#             )
#         )
#     return singularity_rep.representation


# @config.router.post(
#     path="/execute/sedml",
#     response_model=SimulationExperiment,
#     operation_id="execute-sedml",
#     tags=["Simulation"],
#     summary="Execute sedml",
# )
# async def execute_sedml(
#     uploaded_file: UploadFile, tool_suite: ToolSuites, background_tasks: BackgroundTasks
# ) -> SimulationExperiment:
#     omex_archive: Path = await get_file_from_uploaded_file(uploaded_file=uploaded_file)
#     with tempfile.TemporaryDirectory() as tmp_dir:
#         with zipfile.ZipFile(omex_archive, "r") as zip_ref:
#             zip_ref.extractall(path=tmp_dir)
#         for f in os.listdir(tmp_dir):
#             if f.rsplit(".", 1)[-1] == "sedml":
#                 rep = SimpleSedmlRepresentation.sed_processor(Path(f"{tmp_dir}/{f}"))
#                 pbif = SimpleSedmlCompiler.compile(sedml_repr=rep, tool_suite=tool_suite)
#                 return await run_pbif(
#                     templated_pbif=pbif,
#                     simulator_name=rep.solver_kisao,
#                     loaded_sbml=rep.sbml_path,
#                     background_tasks=background_tasks,
#                     use_interesting=False,
#                 )
#
#     raise HTTPException(status_code=422, detail="Couldn't find any SedML file.")


# @config.router.get(
#     path="/simulation/run/versions",
#     response_model=list[Simulation],
#     operation_id="get-simulation-versions",
#     tags=["Simulations"],
#     summary="Get list of simulations",
# )
# async def get_simulation_versions() -> list[Simulation]:
#     db_service = get_database_service()
#     if db_service is None:
#         logger.error("Simulation database service is not initialized")
#         raise HTTPException(status_code=500, detail="Simulation database service is not initialized")
#
#     try:
#         simulations: list[Simulation] = await db_service.list_simulations()
#         return simulations
#     except Exception as e:
#         logger.exception("Error getting simulations")
#         raise HTTPException(status_code=500, detail=str(e)) from e
