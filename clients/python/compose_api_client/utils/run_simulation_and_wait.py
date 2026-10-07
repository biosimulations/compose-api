import asyncio
from typing import Tuple

from compose_api_client import Client
from compose_api_client.api.results import (
    get_simulation_results_file,
    get_simulation_status,
)
from compose_api_client.api.simulation import run_simulation
from compose_api_client.models import (
    BodyRunSimulation,
    HpcRun,
    HTTPValidationError,
    JobStatus,
    SimulationExperiment,
)
from compose_api_client.types import File, Response


async def _get_current_status(client: Client, simulation_id: int) -> HpcRun:
    response = await get_simulation_status.asyncio_detailed(
        client=client, simulation_id=simulation_id
    )
    # Allow 404, since it means simulation has not been submitted to SLURM
    if response.status_code != 200 and response.status_code != 404:
        raise RuntimeError(
            f"Could not get status for simulation id {simulation_id}. Response {response.status_code}: {response.content}"
        )
    return response.parsed


sleep_interval = 2


async def async_call(
    experiment_file: File,
    client: Client,
    interval: float = 1.0,
    seconds_to_wait: int = 10 * 60,
) -> Tuple[Response[HTTPValidationError], SimulationExperiment]:
    response = await run_simulation.asyncio_detailed(
        client=client,
        interval_time=interval,
        body=BodyRunSimulation(uploaded_file=experiment_file),
    )
    sim_experiment = response.parsed
    if response.status_code != 200 or response.parsed is None:
        raise RuntimeError(
            f"Simulation submission failed, {response.status_code}: {response.content}"
        )

    current_status = await _get_current_status(
        client, sim_experiment.simulation_database_id
    )
    num_loops = 0
    loops_to_wait = seconds_to_wait / sleep_interval
    while current_status is None and num_loops < loops_to_wait:
        print("Waiting for simulation to be submitted to slurm.")
        await asyncio.sleep(sleep_interval)
        current_status = await _get_current_status(
            client, sim_experiment.simulation_database_id
        )
        num_loops += 1

    if current_status is None:
        raise RuntimeError(
            f"Simulation has still not been submitted to slurm, and client wait time of {sleep_interval * loops_to_wait} seconds expired."
        )

    print("Simulation has been submitted to slurm.")
    num_loops = 0
    while current_status.status != JobStatus.COMPLETED and num_loops < loops_to_wait:
        await asyncio.sleep(sleep_interval)
        current_status = await _get_current_status(
            client, sim_experiment.simulation_database_id
        )
        num_loops += 1

        incomplete_statuses = {
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMEOUT,
            JobStatus.OUT_OF_MEMORY,
        }
        if current_status.status in incomplete_statuses:
            raise RuntimeError(f"Simulation stopped with status: {current_status}")

        print(
            f"Waited {num_loops * sleep_interval} seconds for simulation to complete. Current status: {current_status}"
        )

    current_status = await _get_current_status(
        client, sim_experiment.simulation_database_id
    )
    if current_status.status != JobStatus.COMPLETED:
        raise RuntimeError(f"Simulation has not completed: {current_status}")

    results: Response[
        HTTPValidationError
    ] = await get_simulation_results_file.asyncio_detailed(
        client=client, simulation_id=sim_experiment.simulation_database_id
    )

    print("Simulation has completed.")

    if results.status_code != 200:
        raise RuntimeError(f"Could not get simulation results: {results}")
    return results, sim_experiment
