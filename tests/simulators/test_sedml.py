"""The gate for biosim-toolkit at level `tested` (registry/manifest.yaml): a SED-ML task translated by
process-bigraph-lang (`sedml translate`, the Ciliberto 2003 project) run inside the built registry_env image, once on
each generic solver. The generic step solves; biosim-toolkit's steps write the SED-ML report and plots; COPASI,
Tellurium and VCell agree (docs/plan-sedml.md, phase 2; docs/plan-vcell-ode.md). The archives are
tests/fixtures/resources/sedml/Ciliberto2003.<solver>.omex, regenerated with process-bigraph-lang's
`sedml translate ... -o dir/` when the translation changes."""

import csv
import io
import json
import os
import zipfile

import pytest
from compose_api_client import Client
from compose_api_client.api.simulation import run_simulation
from compose_api_client.models import BodyRunSimulation
from compose_api_client.types import File

from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.data_service import DataService
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import Simulator
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.simulators.utils import check_experiment_run, test_dir

FIXTURES = os.path.join(test_dir, "fixtures", "resources", "sedml")


def _report(results_zip: bytes) -> dict[str, list[float]]:
    with zipfile.ZipFile(io.BytesIO(results_zip)) as z:
        names = z.namelist()
        report = next(n for n in names if n.endswith("reports/simulation_1/report.csv"))
        plots = sorted(n.rsplit("/", 1)[1] for n in names if "/plots/simulation_1/" in n)
        assert plots == [f"Figure_3{x}.plotly.json" for x in "abcd"]
        figure = json.loads(z.read(next(n for n in names if n.endswith("Figure_3a.plotly.json"))))
        assert [t["name"] for t in figure["data"]] == ["Sic1", "SBF", "Clb2", "Cln"]
        rows = list(csv.reader(io.StringIO(z.read(report).decode())))
    return {label: [float(r[i]) for r in rows[1:]] for i, label in enumerate(rows[0])}


def _score(a: list[float], b: list[float]) -> float:
    """The platform's closeness score (docs/plan-sedml.md, D4): below 1 is close."""
    atol = max(1e-3, max(abs(x) for x in a) * 1e-5, max(abs(x) for x in b) * 1e-5)
    return max(abs(x - y) / (atol + 1e-4 * abs(y)) for x, y in zip(a, b, strict=True))


@pytest.mark.slurm
@pytest.mark.cluster_only
@pytest.mark.asyncio
async def test_sedml_task_on_copasi_tellurium_and_vcell(
    in_memory_api_client: Client,
    database_service: DatabaseServiceSQL,
    simulation_service_slurm: SimulationServiceHpc,
    job_monitor: JobMonitor,
    data_service: DataService,
    simulator: Simulator,
) -> None:
    reports = {}
    for solver in ("copasi", "tellurium", "vcell"):
        with open(os.path.join(FIXTURES, f"Ciliberto2003.{solver}.omex"), "rb") as f:
            sim_experiment = await run_simulation.asyncio(
                client=in_memory_api_client,
                interval_time=1.0,
                body=BodyRunSimulation(uploaded_file=File(file_name=f"Ciliberto2003.{solver}.omex", payload=f)),
            )
        results = await check_experiment_run(
            sim_experiment=sim_experiment, in_memory_api_client=in_memory_api_client, seconds_to_wait=600
        )
        reports[solver] = _report(results.content)
        assert len(reports[solver]) == 21 and len(reports[solver]["Time (min)"]) == 201
    for other in ("tellurium", "vcell"):
        far = {
            label: s
            for label in reports["copasi"]
            if (s := _score(reports["copasi"][label], reports[other][label])) >= 1
        }
        assert not far, f"COPASI and {other} disagree: {far}"
