import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile

from compose_api.authentication import (
    AuthenticatedPrincipal,
    OptionalPrincipal,
    describe_caller,
    get_optional_principal,
)
from compose_api.common.gateway.models import RouterConfig
from compose_api.common.gateway.utils import get_simulation_request_from_uploaded_file, wrap_document_in_omex
from compose_api.config import get_settings
from compose_api.dependencies import (
    get_database_service,
    get_job_monitor,
    get_required_database_service,
    get_simulation_service,
)
from compose_api.environments import lifecycle
from compose_api.environments.admission import standing_for
from compose_api.environments.versions import VersionUnavailableError, chosen_version, environment_of, prebuilt_images
from compose_api.registry.environments import load_environments, offered
from compose_api.registry.manifest import SERVICE_BUNDLE, load_manifest
from compose_api.registry.resolver import covering_environment, needed_entries
from compose_api.registry.validation import (
    AddressPolicy,
    SubmissionRejectedError,
    class_targets,
    find_violations,
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

REJECTED_RESPONSE = {
    "description": "The submission cannot run. For a problem with the request itself (empty file, unsupported type, "
    "interval out of range) `detail` is a string. For a problem with its contents (unreadable archive, or processes "
    "the registry does not allow) `detail` is an object with a `message` and a `violations` list naming each address."
}


async def _named_environment(environment: str | None, simulator: str | None) -> tuple[str | None, str | None]:
    """The prebuilt simulator a request's `environment` and `simulator` name (None: the shared environment, or none
    named), and the undeclared composed environment it names (a mash-up), if it does. `environment` names any
    environment this deployment offers or the database holds; `simulator` is the older name for a prebuilt one, kept
    for a release (docs/plan-environment-composition.md, D7.1). A prebuilt one is offered when it has a default
    version (D8.3). A 400 when they disagree or the name is unknown."""
    images = await prebuilt_images(get_database_service())
    if simulator is not None and simulator not in images:
        offered_here = ", ".join(sorted(images)) or "none"
        raise HTTPException(
            status_code=400, detail=f"unknown simulator {simulator!r}; this deployment offers: {offered_here}"
        )
    if environment is None:
        return simulator, None
    spec = next((e for e in load_environments().environments if e.name == environment), None)
    if spec is None and await _is_mash_up(environment):
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


async def _inferred(
    path: Path,
    file_type: SimulationFileType,
    principal: AuthenticatedPrincipal | None,
    background_tasks: BackgroundTasks,
) -> _Inferred:
    """The environment a run that names none uses, from the classes its documents name (registry/resolver.py): the
    shared environment for everything it covers, as before, then the smallest declared one, then a mash-up that
    covers them. Nothing covering entries that can be composed, the mash-up of exactly those is made for the run
    (step 7b, D7.4): only for a signed-in caller (D7.5); its build follows in the background. Anything else (an
    unreadable submission, an entry that cannot be composed) goes to the shared environment, whose validation says
    why it cannot run."""
    manifest = load_manifest()
    try:
        targets = class_targets(path, file_type)
        refused = any(v.always_rejected for v in find_violations(path, file_type, manifest))
    except SubmissionRejectedError:
        return _Inferred()
    needed = needed_entries(targets, manifest)
    database_service = get_database_service()
    mash_ups = await lifecycle.mash_up_specs(database_service) if database_service is not None else []
    images = await prebuilt_images(database_service)
    covering = covering_environment(
        needed, manifest, load_environments(), offered=lambda spec: offered(spec, images), mash_ups=mash_ups
    )
    if covering is not None:
        if covering.kind == "prebuilt":
            return _Inferred(simulator=covering.name)
        return _Inferred(mash_up=covering.name) if covering.kind == "mash-up" else _Inferred()
    # nothing is made for a run validation will refuse anyway: an unsafe address, or a class under no entry
    unregistered = any(manifest.entry_for_module(t.rpartition(".")[0]) is None for t in targets)
    if not needed or refused or unregistered or database_service is None or lifecycle.composable(needed, manifest):
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


def _checked_options(
    simulator: str | None, interval_time: float, tags: list[str] | None, description: str | None
) -> tuple[list[str], str | None]:
    """The request's own parameters, checked before its file is read: a 400 for any the service does not accept."""
    try:
        run_tags, run_description = clean_tags(tags), clean_description(description)
    except LabelError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if interval_time < 0 or interval_time > 1000:
        raise HTTPException(status_code=400, detail="Invalid interval time, it has to be between 0 and 1000")
    return run_tags, run_description


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
    run_tags, run_description = _checked_options(simulator, interval_time, tags, description)
    simulator, composed = await _named_environment(environment, simulator)
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
            simulation_request.request_file_path, simulation_request.simulation_file_type, principal, background_tasks
        )
        simulator, composed, environment_version = inferred.simulator, inferred.mash_up, inferred.version
    simulation_request.end_time_point = interval_time
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
        )
    except SubmissionRejectedError as e:
        simulation_request.request_file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail={"message": e.message, "violations": [v.model_dump() for v in e.violations]},
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
