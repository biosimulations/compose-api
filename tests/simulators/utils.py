import math
import os
import tempfile
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import numpy
from compose_api_client import Client
from compose_api_client.api.results import get_simulation_results_file
from compose_api_client.ext import AsyncComposeSession
from compose_api_client.models import HTTPValidationError, SimulationExperiment
from compose_api_client.types import Response

from compose_api.common.gateway.models import Namespace
from compose_api.config import get_settings
from compose_api.dependencies import get_required_database_service
from compose_api.observability.ingest import EventIngester
from compose_api.simulation.hpc_utils import get_internal_experiment_dir


async def check_experiment_run(
    sim_experiment: Any, in_memory_api_client: Client, seconds_to_wait: int = 120
) -> Response[HTTPValidationError]:
    """Wait for the simulation through the client's application layer (``ext``), assert it completed, and return
    its results response."""
    assert isinstance(sim_experiment, SimulationExperiment)
    session = AsyncComposeSession(client=in_memory_api_client)
    state = await session.wait(sim_experiment.simulation_database_id, poll=2, timeout=seconds_to_wait)
    assert state.ok, f"simulation {sim_experiment.simulation_database_id} ended {state.status}"

    results: Response[HTTPValidationError] = await get_simulation_results_file.asyncio_detailed(
        client=in_memory_api_client, simulation_id=sim_experiment.simulation_database_id
    )
    assert results.status_code == 200
    await _check_run_events(session, sim_experiment.simulation_database_id)
    return results


async def _check_run_events(session: AsyncComposeSession, simulation_id: int) -> None:
    """The run has a trace and datasets (docs/plan-observability.md O3, O5): the API's dispatch event, the job
    script's own events and its manifest, ingested from the experiment directory as the service's polling loop does."""
    namespace = Namespace(get_settings().namespace)
    ingester = EventIngester(get_required_database_service(), lambda e: get_internal_experiment_dir(e, namespace))
    await ingester.ingest_once()
    page = await session.events(simulation_id)
    names = {e.event for e in page.events}
    assert {"dispatch.submitted", "job.start", "job.end"} <= names, f"events of simulation {simulation_id}: {names}"
    tree = await session.trace(simulation_id)
    assert [root.span.name for root in tree.roots] == ["job"]
    assert tree.roots[0].span.status == "ok"
    datasets = (await session.datasets(simulation_id=simulation_id)).datasets
    paths = {d.path for d in datasets}
    assert "results.zip" in paths and any(p.startswith("output/") for p in paths), paths
    assert all(d.sha256 and d.size_bytes is not None for d in datasets)


def assert_test_sim_results(
    archive_results: os.PathLike[str],
    expected_csv_path: os.PathLike[str],
    temp_dir: os.PathLike[str],
    difference_tolerance: float = 1e-9,
) -> None:
    with ZipFile(archive_results) as zip_archive:
        zip_archive.extractall(temp_dir)
    experiment_result = f"{temp_dir}/results.csv"
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


async def get_results_and_compare_copasi(api_client: Client, sim_id: int = 0, file_result: Any = None) -> None:
    if file_result is None:
        file_result = await get_simulation_results_file.asyncio_detailed(client=api_client, simulation_id=sim_id)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        experiment_results = temp_dir_path / Path("experiment_results.zip")
        with open(experiment_results, "wb") as results_file:
            results_file.write(file_result.content)
        report_csv_file = Path(os.path.join(test_dir, "fixtures/resources/report.csv"))
        assert_test_sim_results(
            archive_results=experiment_results,
            expected_csv_path=report_csv_file,
            temp_dir=temp_dir_path,
            difference_tolerance=1e-4,
        )


test_dir = os.path.dirname(__file__).rsplit("/", 1)[0]
