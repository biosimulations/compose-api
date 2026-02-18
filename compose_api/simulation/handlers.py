import asyncio
import logging
import random
import shutil
import string
import tempfile
import zipfile
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException
from pbest.containerization.container_constructor import generate_container_def_file
from pbest.utils.input_types import (
    ContainerizationEngine,
    ContainerizationProgramArguments,
    ContainerizationTypes,
)

from compose_api.common.gateway.utils import allow_list
from compose_api.db.database_service import DatabaseService
from compose_api.dependencies import (
    get_database_service,
    get_required_database_service,
    get_required_job_monitor,
    get_required_simulation_service,
)
from compose_api.simulation.hpc_utils import get_correlation_id, get_experiment_id, get_singularity_hash
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import (
    HpcRun,
    JobStatus,
    JobType,
    PBAllowList,
    RegisteredSimulators,
    Simulation,
    SimulationExperiment,
    SimulationFileType,
    SimulationRequest,
)
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
    pb_allow_list: PBAllowList,
    background_tasks: BackgroundTasks,
) -> SimulationExperiment:
    with tempfile.TemporaryDirectory(delete=False) as tmp_dir:
        singularity_rep = generate_container_def_file(
            ContainerizationProgramArguments(
                input_file_path=str(simulation_request.request_file_path),
                working_directory=Path(tmp_dir),
                containerization_type=ContainerizationTypes.SINGLE,
                containerization_engine=ContainerizationEngine.APPTAINER,
            ),
        )
        # simulation_request.omex_archive = Path(tmp_dir + f"/{os.path.basename(simulation_request.omex_archive.name)}")

    simulator_db = database_service.get_simulator_db()
    simulator_version = await simulator_db.get_simulator_by_def_hash(get_singularity_hash(singularity_rep))
    if simulator_version is None:
        # bi_graph_packages = await database_service.get_package_db().list_packages_from_dependencies(
        #     dependencies=pbest_dependencies
        # )
        # if len(bi_graph_packages) != (len(experiment_dep.pypi_dependencies) + len(experiment_dep.conda_dependencies)):
        #     raise LookupError(f"Not all dependencies are in database: {experiment_dep}, {bi_graph_packages}")

        simulator_version = await simulator_db.insert_simulator(singularity_rep)

    random_string_7_hex = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
    experiment_id = get_experiment_id(simulator=simulator_version, random_str=random_string_7_hex)

    simulation = await simulator_db.insert_simulation(
        sim_request=simulation_request, experiment_id=experiment_id, simulator_version=simulator_version
    )

    async def perform_job() -> None:
        await _dispatch_job(
            database_service=database_service,
            job_monitor=job_monitor,
            simulation=simulation,
            simulation_service_slurm=simulation_service_slurm,
            experiment_id=experiment_id,
        )

    def remove_temp_dir() -> None:
        shutil.rmtree(tmp_dir)

    # Tasks are executed in order, https://www.starlette.dev/background/
    background_tasks.add_task(perform_job)
    background_tasks.add_task(remove_temp_dir)

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
            omex.writestr(data=templated_pbif, zinfo_or_arcname=f"{simulator_name}.pbif")
            if use_interesting:
                omex.write(loaded_sbml.absolute(), arcname="interesting.sbml")
            else:
                omex.write(loaded_sbml.absolute(), arcname=loaded_sbml.name)
        if omex.filename is None:
            raise HTTPException(500, "Can't create omex file.")
        simulator_request = SimulationRequest(
            request_file_path=Path(omex.filename), simulation_file_type=SimulationFileType.OMEX
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
                pb_allow_list=PBAllowList(allow_list=allow_list),
                background_tasks=background_tasks,
            )
        except Exception as e:
            logger.exception(msg=f"Failed to start {simulator_name} run", exc_info=e)
            raise HTTPException(500)


async def _dispatch_job(
    database_service: DatabaseService,
    job_monitor: JobMonitor,
    simulation_service_slurm: SimulationService,
    simulation: Simulation,
    experiment_id: str,
) -> None:
    simulator_version = simulation.simulator_version
    hpc_db = database_service.get_hpc_db()
    simulator_hpc_id = await hpc_db.get_hpcrun_id_by_simulator_id(simulator_id=simulator_version.database_id)
    random_string_7_hex = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure

    if simulator_hpc_id is None:
        hpc_run = await simulation_service_slurm.build_container(
            simulator_version=simulator_version, random_str=random_string_7_hex
        )

        wait_time = 0
        current_status = hpc_run.status
        job_queue: asyncio.Queue[HpcRun] = asyncio.Queue()
        job_monitor.internal_subscribe(job_queue, hpc_run.slurmjobid)
        while current_status != JobStatus.COMPLETED:
            wait_time += 1
            try:
                current_status = (await asyncio.wait_for(job_queue.get(), timeout=60)).status
            except TimeoutError:
                # If no status update from monitor, get most recent from DB of absolute truth
                latest_hpc = await hpc_db.get_hpcrun_by_slurmjobid(hpc_run.slurmjobid)
                if latest_hpc is None:
                    raise Exception(
                        f"Can't get HPC Run with jobID {hpc_run} for container build {simulator_version.singularity_def_hash}"  # noqa: E501
                    )
                current_status = latest_hpc.status

            if current_status == JobStatus.FAILED:
                raise Exception(f"Building container for simulator {simulator_version} has failed.")
            elif wait_time == 30:
                raise Exception(
                    f"Building container for simulator {simulator_version} took to long, job at status of {current_status}."  # noqa: E501
                )
        job_monitor.internal_unsubscribe(hpc_run.slurmjobid)

    sim_slurmjobid = await simulation_service_slurm.submit_simulation_job(
        simulation=simulation,
        experiment_id=experiment_id,
    )

    correlation_id = get_correlation_id(random_string=random_string_7_hex, job_type=JobType.SIMULATION)
    _hpcrun = await hpc_db.insert_hpcrun(
        slurmjobid=sim_slurmjobid,
        job_type=JobType.SIMULATION,
        ref_id=simulation.database_id,
        correlation_id=correlation_id,
    )
