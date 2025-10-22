import asyncio
import math
import os
from typing import Any
from zipfile import ZipFile

import numpy

from compose_api.api.client import Client
from compose_api.api.client.api.simulations import get_simulation_results_file, get_simulation_status
from compose_api.api.client.models import HpcRun, HTTPValidationError, JobStatus, SimulationExperiment
from compose_api.api.client.types import Response


async def check_experiment_run(sim_experiment: Any, in_memory_api_client: Client) -> Response[HTTPValidationError]:
    """
    Checks that the simulation is running, asserts that it does not fail, and returns its results.
    Args:
        sim_experiment:
        in_memory_api_client:

    Returns:

    """
    assert isinstance(sim_experiment, SimulationExperiment)

    current_status = await get_simulation_status.asyncio(
        client=in_memory_api_client, simulation_id=sim_experiment.simulation_database_id
    )

    if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
        raise TypeError()

    num_loops = 0
    while current_status.status != JobStatus.COMPLETED and num_loops < 30:
        await asyncio.sleep(2)
        current_status = await get_simulation_status.asyncio(
            client=in_memory_api_client, simulation_id=sim_experiment.simulation_database_id
        )
        num_loops += 1

        if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
            raise TypeError()
        if current_status.status == JobStatus.FAILED:
            raise RuntimeError("Simulation failed")

    current_status = await get_simulation_status.asyncio(
        client=in_memory_api_client, simulation_id=sim_experiment.simulation_database_id
    )

    if not isinstance(current_status, HpcRun) or not isinstance(current_status.status, JobStatus):
        raise TypeError()

    assert current_status.status == JobStatus.COMPLETED

    results: Response[HTTPValidationError] = await get_simulation_results_file.asyncio_detailed(
        client=in_memory_api_client, experiment_id=sim_experiment.experiment_id
    )
    assert results.status_code == 200
    return results


def assert_test_sim_results(
    archive_results: os.PathLike[str],
    expected_csv_path: os.PathLike[str],
    temp_dir: os.PathLike[str],
    difference_tolerance: float = 1e-9,
) -> None:
    with ZipFile(archive_results) as zip_archive:
        zip_archive.extractall(temp_dir)
    experiment_result = f"{temp_dir}/report.csv"
    experiment_numpy = numpy.genfromtxt(experiment_result, delimiter=",", dtype=object)
    report_numpy = numpy.genfromtxt(expected_csv_path, delimiter=",", dtype=object)
    assert report_numpy.shape == experiment_numpy.shape
    r, c = report_numpy.shape
    for i in range(r):
        for j in range(c):
            report_val = report_numpy[i, j].decode("utf-8")
            experiment_val = experiment_numpy[i, j].decode("utf-8")
            try:
                f_report = float(report_val)
                f_exp = float(experiment_val)
                assert math.isclose(f_report, f_exp, rel_tol=0, abs_tol=difference_tolerance)
            except ValueError:
                assert report_val == experiment_val  # Must be string portion of report then (columns)


test_dir = os.path.dirname(__file__).rsplit("/", 1)[0]
