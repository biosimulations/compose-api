import asyncio
import logging
import random
import string
import tempfile
import zipfile
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException

from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseService
from compose_api.db.services.hpc_db import HPCDatabaseService
from compose_api.db.services.simulators_db import SimulatorDatabaseService
from compose_api.dependencies import (
    get_database_service,
    get_required_database_service,
    get_required_job_monitor,
    get_required_simulation_service,
    get_submission_worker,
)
from compose_api.environments.versions import version_for
from compose_api.observability.api_events import record_api_event
from compose_api.registry.manifest import SERVICE_BUNDLE
from compose_api.simulation import builds, images, staging
from compose_api.simulation.hpc_utils import get_experiment_id
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.labels import labels
from compose_api.simulation.models import (
    HpcRun,
    JobStatus,
    JobType,
    RegisteredSimulators,
    RemoteContainerImage,
    SimulationCancellation,
    SimulationExperiment,
    SimulationFileType,
    SimulationRequest,
    SimulatorVersion,
    SubmissionSpec,
    SubmissionState,
)
from compose_api.simulation.prebuilt import prebuilt_image_of
from compose_api.simulation.simulation_service import SimulationService

logger = logging.getLogger(__name__)


# -- roundtrip job handlers that both call the services and return the relative endpoint's DTO -- #


async def get_simulator_versions() -> RegisteredSimulators:
    sim_db_service = get_database_service()
    if sim_db_service is None:
        logger.error("Simulation database service is not initialized")
        raise HTTPException(status_code=500, detail="Simulation database service is not initialized")
    try:
        simulators = await sim_db_service.get_simulator_db().list_simulators()
        return RegisteredSimulators(versions=simulators)
    except Exception as e:
        logger.exception("Error getting list of simulation versions")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def run_simulation(
    simulation_request: SimulationRequest,
    database_service: DatabaseService,
    simulation_service_slurm: SimulationService,
    job_monitor: JobMonitor,
    background_tasks: BackgroundTasks,
    *,
    queue: str = "interactive",
    priority: int = 0,
    requested_by: str | None = None,
) -> SimulationExperiment:
    """Record a run and queue it for the submission worker; its ids. ``queue`` and ``priority`` place it in line
    (docs/plan-durable-submission.md, Q3); ``requested_by`` is the caller's subject, kept for fair scheduling."""
    # the environment version it runs in (docs/plan-environment-versions.md): the one it names, or the default
    version, simulator_version = await version_for(
        database_service, simulation_request.simulator, simulation_request.environment_version
    )
    simulation_request = simulation_request.model_copy(
        update={"labels": {**simulation_request.labels, "environment_version": version.label}}
    )

    random_string_7_hex = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
    experiment_id = get_experiment_id(simulator=simulator_version, random_str=random_string_7_hex)

    # Durable before the response (docs/plan-durable-submission.md, Q1): the files staged, and the simulation recorded
    # with its `requested` submission in one transaction. The submission worker takes it from there, after a restart
    # too, so nothing here outlives the request.
    staged_request, on_store = staging.stage_request(simulation_request, experiment_id)
    simulation = await database_service.get_simulator_db().insert_simulation(
        sim_request=staged_request,
        experiment_id=experiment_id,
        simulator_version=simulator_version,
        environment_version_id=version.database_id,
        submission=SubmissionSpec(staged_on_store=on_store, queue=queue, priority=priority, requested_by=requested_by),
    )
    worker = get_submission_worker()
    if worker is not None:
        worker.kick()

    return SimulationExperiment(
        simulation_database_id=simulation.database_id,
        simulator_database_id=simulator_version.database_id,
    )


async def run_curated_pbif(
    templated_pbif: str,
    simulator_name: str,
    background_tasks: BackgroundTasks,
    loaded_sbml: Path,
    use_interesting: bool = True,
) -> SimulationExperiment:
    # Create OMEX with all necessary files
    with tempfile.TemporaryDirectory(delete=False) as tmp_dir:
        with zipfile.ZipFile(tmp_dir + "/input.omex", "w") as omex:
            omex.writestr(data=templated_pbif, zinfo_or_arcname=f"{simulator_name}.pbg")
            if use_interesting:
                omex.write(loaded_sbml.absolute(), arcname="interesting.sbml")
            else:
                omex.write(loaded_sbml.absolute(), arcname=loaded_sbml.name)
        if omex.filename is None:
            raise HTTPException(500, "Can't create omex file.")
        simulator_request = SimulationRequest(
            request_file_path=Path(omex.filename),
            simulation_file_type=SimulationFileType.OMEX,
            is_batch=False,
            labels=labels(source="curated", solver=simulator_name.lower(), environment=SERVICE_BUNDLE),
        )

        try:
            sim_service = get_required_simulation_service()
            db_service = get_required_database_service()
            job_monitor = get_required_job_monitor()
        except ValueError as e:
            logger.exception(msg=f"Failed to initialize {simulator_name} run.", exc_info=e)
            raise HTTPException(status_code=500, detail=str(e))

        try:
            return await run_simulation(
                simulation_request=simulator_request,
                database_service=db_service,
                simulation_service_slurm=sim_service,
                job_monitor=job_monitor,
                background_tasks=background_tasks,
            )
        except Exception as e:
            logger.exception(msg=f"Failed to start {simulator_name} run", exc_info=e)
            raise HTTPException(500)


#: One build at a time per container definition: runs submitted together with a new definition (a SED-ML comparison's
#: solvers) wait for the first one's build instead of starting their own (they would share its files on the cluster).
_build_locks: dict[str, asyncio.Lock] = {}


async def ensure_image(
    simulator_version: SimulatorVersion,
    *,
    database_service: DatabaseService,
    simulation_service_slurm: SimulationService,
    job_monitor: JobMonitor,
    random_string: str,
) -> None:
    """Make the simulator's image available: a run's preprocess, and a build invoked on its own (E5).

    Check, then fetch under the hash's lock (held in Postgres, so across API processes; _download_or_build_container
    checks again): submissions that arrive while the image is fetched wait for it instead of fetching it over the file
    the first one's jobs mount.
    """
    simulator_db = database_service.get_simulator_db()
    if await _image_ready(simulator_db, simulator_version):
        return
    async with simulator_db.container_lock(simulator_version.container_def_hash):
        await _download_or_build_container(
            simulation_service_slurm=simulation_service_slurm,
            simulator_version=simulator_version,
            hpc_db=database_service.get_hpc_db(),
            job_monitor=job_monitor,
            random_string=random_string,
            simulator_db=simulator_db,
        )


async def _image_ready(simulator_db: SimulatorDatabaseService, simulator_version: SimulatorVersion) -> bool:
    """Whether the simulator's image is there to run from: an available SIF (docs/plan-environment-builds.md, E3), or
    for a Docker engine a recorded pull."""
    if images.tracked():
        return await images.available_sif(simulator_db, simulator_version) is not None
    return await simulator_db.get_downloaded_simulator(simulator_id=simulator_version.database_id) is not None


async def _download_or_build_container(
    simulation_service_slurm: SimulationService,
    simulator_version: SimulatorVersion,
    hpc_db: HPCDatabaseService,
    job_monitor: JobMonitor,
    random_string: str,
    simulator_db: SimulatorDatabaseService,
) -> None:
    lock = _build_locks.setdefault(simulator_version.container_def_hash, asyncio.Lock())
    async with lock:
        # another run may have fetched it while this one waited; a failed build left nothing, so it is tried again
        if await _image_ready(simulator_db, simulator_version):
            return
        logger.info(
            f"Simulator {simulator_version.database_id} is being downloaded from "
            f"{RemoteContainerImage.from_container_version(simulator_version)}."
        )
        download_succeeded = False
        # a prebuilt simulator is pulled from its own image; any other from the shared repository by hash
        prebuilt = prebuilt_image_of(simulator_version.container_def)
        try:
            await simulation_service_slurm.download_container(
                RemoteContainerImage.from_container_version(
                    simulator_version, source_url=f"docker://{prebuilt}" if prebuilt else None
                )
            )
            download_succeeded = True
        except Exception as e:
            logger.exception(
                "Failed to download simulator slurm container, will attempt to build container.", exc_info=e
            )

        if download_succeeded:
            if images.tracked() and await images.record_sif(simulator_db, simulator_version) is None:
                raise RuntimeError(
                    f"The pull for simulator {simulator_version.database_id} left no image at "
                    f"{images.sif_location(simulator_version)}"
                )
            return
        # a build of this definition that has not finished (started by another API process, or before a restart)
        # is joined: its run's status is in the database, whichever backend it runs on
        in_flight = await hpc_db.get_hpcrun_by_ref(
            ref_id=simulator_version.database_id, job_type=JobType.BUILD_CONTAINER
        )
        try:
            if in_flight is not None and in_flight.status not in builds.FINISHED:
                logger.info(f"Joining build run {in_flight.database_id} of simulator {simulator_version.database_id}")
                build: HpcRun | None = await builds.wait_for_run(in_flight, hpc_db)
            elif get_settings().build_backend == "k8s":
                from compose_api.simulation.build_k8s import build_and_wait

                build = await build_and_wait(simulator_version, hpc_db, random_string)
            else:
                build = await _build_container_and_wait(
                    simulation_service_slurm=simulation_service_slurm,
                    simulator_version=simulator_version,
                    hpc_db=hpc_db,
                    job_monitor=job_monitor,
                    random_prefix=random_string,
                )
        except Exception as e:
            logger.exception("Failed to build simulator container", exc_info=e)
            raise e
        build_id = build.database_id if build is not None else None
        if images.tracked() and await images.record_sif(simulator_db, simulator_version, hpcrun_id=build_id) is None:
            raise RuntimeError(
                f"The build of simulator {simulator_version.database_id} (run {build_id}) completed without writing "
                f"{images.sif_location(simulator_version)}"
            )


async def _build_container_and_wait(
    simulation_service_slurm: SimulationService,
    simulator_version: SimulatorVersion,
    hpc_db: HPCDatabaseService,
    job_monitor: JobMonitor,
    random_prefix: str,
) -> HpcRun | None:
    hpc_run = await simulation_service_slurm.build_container(
        simulator_version=simulator_version, random_str=random_prefix
    )

    slurmjobid = hpc_run.slurmjobid
    if slurmjobid is None:
        raise RuntimeError(f"Container build for {simulator_version.container_def_hash} has no SLURM job")
    wait_time = 0
    current_status = hpc_run.status
    job_queue: asyncio.Queue[HpcRun] = asyncio.Queue()
    job_monitor.internal_subscribe(job_queue, slurmjobid)
    while current_status != JobStatus.COMPLETED:
        wait_time += 1
        try:
            current_status = (await asyncio.wait_for(job_queue.get(), timeout=60)).status
        except TimeoutError:
            # If no status update from monitor, get most recent from DB of absolute truth
            latest_hpc = await hpc_db.get_hpcrun_by_slurmjobid(slurmjobid)
            if latest_hpc is None:
                raise Exception(
                    f"Can't get HPC Run with jobID {hpc_run} for container build {simulator_version.container_def_hash}"
                )
            current_status = latest_hpc.status

        if current_status == JobStatus.FAILED:
            raise Exception(f"Building container for simulator {simulator_version} has failed.")
        elif wait_time == 30:
            raise Exception(
                f"Building container for simulator {simulator_version} took to long, job at status of {current_status}."
            )
    job_monitor.internal_unsubscribe(slurmjobid)
    return hpc_run


class CancelRefusedError(Exception):
    """The run cannot be cancelled in its current state; the message says why (the route's 409)."""


class CancelUnavailableError(Exception):
    """SLURM could not be asked to cancel the job (unreachable, or scancel failed); trying again may work."""


async def cancel_simulation(
    simulation_id: int,
    requested_by: str,
    database_service: DatabaseService,
    simulation_service_slurm: SimulationService | None,
) -> SimulationCancellation:
    """Cancel a run the caller may read (the route checks).

    - **Queued** (``requested`` or ``preparing``): withdrawn before any sbatch, under the submission's lock; the run is
      CANCELLED at once and its staged files are removed.
    - **Being submitted** (``submitting``): refused, since sbatch may be in flight; a moment later the run has its job.
    - **In SLURM**: ``scancel``. The job monitor records CANCELLED, with its ``slurm.cancelled`` event, when SLURM
      reports it. This answers that the cancel was requested: a job that finished in the meantime keeps its status.
    - **Finished**: refused.

    Who cancelled is logged here only: the run's message and events are readable by anyone who may read the run.
    """
    hpc_db = database_service.get_hpc_db()
    reason = "Cancelled by a signed-in user"
    submission = await hpc_db.get_submission(simulation_id)
    if submission is not None and submission.state in (SubmissionState.REQUESTED, SubmissionState.PREPARING):
        if await hpc_db.withdraw_submission(simulation_id, reason) is not None:
            staging.remove_staging(submission.experiment_id, submission.staged_on_store)
            logger.info(f"Simulation {simulation_id}: withdrawn from the submission queue, by {requested_by}")
            return SimulationCancellation(simulation_id=simulation_id, withdrawn=True)
        submission = await hpc_db.get_submission(simulation_id)  # it moved on meanwhile; answer its new state
    if submission is not None and submission.state == SubmissionState.SUBMITTING:
        raise CancelRefusedError(f"Simulation {simulation_id} is being submitted to SLURM; cancel again in a moment.")
    hpc_run = await hpc_db.get_hpcrun_by_ref(simulation_id, JobType.SIMULATION)
    if hpc_run is not None and hpc_run.status in builds.FINISHED:
        status = hpc_run.status.value if hpc_run.status else "finished"
        raise CancelRefusedError(f"Simulation {simulation_id} has already finished ({status}).")
    if hpc_run is None or hpc_run.slurmjobid is None:
        raise CancelRefusedError(f"Simulation {simulation_id} has no SLURM job to cancel.")
    if simulation_service_slurm is None:
        raise CancelUnavailableError("the simulation service is not running, so SLURM cannot be asked to cancel")
    try:
        await simulation_service_slurm.cancel_simulation_job(hpc_run.slurmjobid)
    except Exception as e:
        logger.exception(f"Simulation {simulation_id}: scancel {hpc_run.slurmjobid} failed")
        raise CancelUnavailableError(f"SLURM could not cancel job {hpc_run.slurmjobid}; try again") from e
    await record_api_event(database_service, hpc_run, "dispatch.cancel_requested", {"slurm_job_id": hpc_run.slurmjobid})
    logger.info(f"Simulation {simulation_id}: scancel {hpc_run.slurmjobid}, requested by {requested_by}")
    return SimulationCancellation(simulation_id=simulation_id, withdrawn=False, slurm_job_id=hpc_run.slurmjobid)
