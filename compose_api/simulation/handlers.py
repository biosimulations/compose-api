import asyncio
import logging
import os.path
import random
import string
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException

from compose_api.btools.bsander.bsandr_utils.input_types import (
    ContainerizationEngine,
    ContainerizationTypes,
    ProgramArguments,
)
from compose_api.btools.bsander.execution import execute_bsander
from compose_api.db.database_service import DatabaseService
from compose_api.dependencies import get_database_service
from compose_api.simulation.hpc_utils import get_correlation_id, get_experiment_id, get_singularity_hash
from compose_api.simulation.job_scheduler import JobMonitor
from compose_api.simulation.models import (
    HpcRun,
    JobStatus,
    JobType,
    PBAllowList,
    RegisteredSimulators,
    Simulation,
    SimulationExperiment,
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
        simulators = await sim_db_service.list_simulators()
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
    background_tasks: BackgroundTasks | None = None,
) -> SimulationExperiment:
    allow_list = pb_allow_list.allow_list

    with tempfile.TemporaryDirectory(delete=False) as tmp_dir:
        singularity_rep, experiment_dep = execute_bsander(
            ProgramArguments(
                input_file_path=str(simulation_request.omex_archive),
                output_dir=tmp_dir,
                containerization_type=ContainerizationTypes.SINGLE,
                containerization_engine=ContainerizationEngine.APPTAINER,
                passlist_entries=allow_list,
            )
        )
        simulation_request.omex_archive = Path(tmp_dir + f"/{os.path.basename(simulation_request.omex_archive.name)}")

    simulator_version = await database_service.get_simulator_by_def_hash(get_singularity_hash(singularity_rep))
    if simulator_version is None:
        simulator_version = await database_service.insert_simulator(singularity_rep, experiment_dep)

    random_string_7_hex = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
    experiment_id = get_experiment_id(simulator=simulator_version, random_str=random_string_7_hex)

    simulation = await database_service.insert_simulation(
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

    if background_tasks:
        background_tasks.add_task(perform_job)
    else:
        await perform_job()

    return SimulationExperiment(
        experiment_id=experiment_id, simulation_id=simulation.database_id, simulator_id=simulator_version.database_id
    )


async def _dispatch_job(
    database_service: DatabaseService,
    job_monitor: JobMonitor,
    simulation_service_slurm: SimulationService,
    simulation: Simulation,
    experiment_id: str,
) -> None:
    simulator_version = simulation.simulator_version
    simulator_hpc_id = await database_service.get_hpcrun_id_by_simulator_id(simulator_id=simulator_version.database_id)
    random_string_7_hex = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure

    if simulator_hpc_id is None:
        build_slurm_id = await simulation_service_slurm.build_container(simulator_version=simulator_version)
        hpc_build_run = await database_service.insert_hpcrun(
            slurmjobid=build_slurm_id,
            job_type=JobType.BUILD_CONTAINER,
            ref_id=simulator_version.database_id,
            correlation_id=get_correlation_id(random_string=random_string_7_hex, job_type=JobType.BUILD_CONTAINER),
        )

        wait_time = 0
        current_status = hpc_build_run.status
        job_queue: asyncio.Queue[HpcRun] = asyncio.Queue()
        job_monitor.internal_subscribe(job_queue, hpc_build_run.slurmjobid)
        while current_status != JobStatus.COMPLETED:
            wait_time += 1
            try:
                current_status = (await asyncio.wait_for(job_queue.get(), timeout=60)).status
                error_message = ""
            except TimeoutError:
                # If no status update from monitor, get most recent from DB of absolute truth
                latest_hpc = await database_service.get_hpcrun_by_slurmjobid(hpc_build_run.slurmjobid)
                if latest_hpc is None:
                    raise Exception(
                        f"Can't get HPC Run with jobID {hpc_build_run.slurmjobid} for container build {simulator_version.singularity_def_hash}"  # noqa: E501
                    )
                current_status = latest_hpc.status
                error_message = latest_hpc.error_message if JobStatus.FAILED else ""
            if current_status == JobStatus.FAILED:
                raise Exception(f"Building container for simulator {simulator_version} has failed:\n\t{error_message}.")
            elif wait_time == 30:
                raise Exception(
                    f"Building container for simulator {simulator_version} took to long, job at status of {current_status}."  # noqa: E501
                )
        job_monitor.internal_unsubscribe(hpc_build_run.slurmjobid)

    sim_slurmjobid = await simulation_service_slurm.submit_simulation_job(
        simulation=simulation,
        database_service=database_service,
        experiment_id=experiment_id,
    )

    correlation_id = get_correlation_id(random_string=random_string_7_hex, job_type=JobType.SIMULATION)
    _hpcrun = await database_service.insert_hpcrun(
        slurmjobid=sim_slurmjobid,
        job_type=JobType.SIMULATION,
        ref_id=simulation.database_id,
        correlation_id=correlation_id,
    )
