"""/sources (docs/plan-sedml.md, phase 4) answered from recorded upstream responses (tests/fixtures/resources/sources):
BioModels search, metadata and archive; a biosimulations.org project, its archive and its original results; and the
run shortcuts, whose comparisons carry the original results as a reference."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from compose_api.common.hpc.models import SlurmJob
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.sedml import sources
from compose_api.sedml.compare import read_report
from compose_api.simulation.models import JobType
from tests.sedml.conftest import needs_translator

RESOURCES = Path(__file__).resolve().parents[1] / "fixtures" / "resources"
RECORDED = RESOURCES / "sources"
PROJECT = "Morphogenesis-checkpoint-continuous-Ciliberto-J-Cell-Biol-2003"


@pytest.fixture(autouse=True)
def recorded(recorded_sources: list[str]) -> list[str]:
    return recorded_sources


@pytest.mark.asyncio
async def test_biomodels_search_metadata_and_cached_archive(client: httpx.AsyncClient, recorded: list[str]) -> None:
    hits = (await client.get("/sources/biomodels/search", params={"q": "repressilator"})).json()
    assert hits[0] == {
        "id": "BIOMD0000000012",
        "name": "Elowitz2000 - Repressilator",
        "format": "SBML",
        "url": "https://www.biomodels.org/BIOMD0000000012",
    }
    info = (await client.get("/sources/biomodels/BIOMD0000000012")).json()
    assert (info["curation"], info["revision"], info["format"]) == ("CURATED", 3, "SBML")
    first = await client.get("/sources/biomodels/BIOMD0000000012/omex")
    again = await client.get("/sources/biomodels/BIOMD0000000012/omex")
    assert first.status_code == 200 and first.content == again.content
    assert recorded.count(f"{sources.BIOMODELS}/model/download/BIOMD0000000012") == 1  # cached by revision
    assert (await client.get("/sources/biomodels/not-an-id")).status_code == 404


@pytest.mark.asyncio
async def test_a_biosimulations_project_and_its_original_results(client: httpx.AsyncClient) -> None:
    (found,) = (await client.get("/sources/biosimulations/projects", params={"q": "ciliberto-j-cell"})).json()
    assert found["id"] == PROJECT
    info = (await client.get(f"/sources/biosimulations/{PROJECT}")).json()
    assert (info["simulator"], info["simulator_version"]) == ("tellurium", "2.2.1")
    reference = (await client.get(f"/sources/biosimulations/{PROJECT}/reference")).json()
    assert list(reference) == ["simulation_1.sedml/report"]
    report = reference["simulation_1.sedml/report"]
    assert len(report) == 21 and len(report["Time (min)"]) == 201 and report["Time (min)"][-1] == 140.0
    assert (await client.get("/sources/biosimulations/nope/omex")).status_code == 404


@needs_translator
@pytest.mark.asyncio
async def test_running_a_project_compares_its_solvers_and_its_original_results(
    client: httpx.AsyncClient, submitted: dict[str, Any], database_service: DatabaseServiceSQL, tmp_path: Path
) -> None:
    response = await client.post(f"/sources/biosimulations/{PROJECT}/run")
    assert response.status_code == 200, response.text
    (comparison,) = response.json()["comparisons"]
    assert comparison["source"] == f"biosimulations:{PROJECT}"
    runs = submitted["runs"]
    assert {r[0].labels["project"] for r in runs} == {PROJECT}

    # both solvers reproduce the original results exactly: the reference's own columns as their reports
    reference = (await client.get(f"/sources/biosimulations/{PROJECT}/reference")).json()["simulation_1.sedml/report"]
    labels = comparison["settings"]["reports"]["report"]["labels"]
    rows = [",".join(json.dumps(label) for label in labels)] + [
        ",".join(repr(reference[label][i]) for label in labels) for i in range(201)
    ]
    hpc_db = database_service.get_hpc_db()
    for n, (_request, sim_id, experiment_id) in enumerate(runs):
        run = await hpc_db.insert_hpcrun(
            slurmjobid=9700 + n, job_type=JobType.SIMULATION, ref_id=sim_id, correlation_id=f"ref-{sim_id}"
        )
        await hpc_db.update_hpcrun_status(
            run.database_id, SlurmJob(job_id=9700 + n, name="x", account="a", user_name="u", job_state="COMPLETED")
        )
        out = (
            tmp_path / "mount" / "test" / "sims" / f"experiment-{experiment_id}" / "output" / "reports" / "simulation_1"
        )
        out.mkdir(parents=True)
        (out / "report.csv").write_text("\n".join(rows) + "\n")
        assert len(read_report((out / "report.csv").read_text())["Total Swe1"]) == 201

    done = (await client.get(f"/comparisons/{comparison['comparison_id']}")).json()
    assert done["status"] == "complete" and done["close"] is True
    assert done["result"]["references"] == ["biosimulations:tellurium"]
    assert done["result"]["close_to_references"] is True
    pair = done["result"]["reports"]["report"]["labels"]["Clb2"]["copasi|biosimulations:tellurium"]
    assert pair == {"score": 0.0, "close": True, "reference": True}

    series = (
        await client.get(f"/comparisons/{comparison['comparison_id']}/series", params={"report": "report"})
    ).json()
    assert sorted(series["solvers"]) == ["copasi", "tellurium"] and list(series["references"]) == [
        "biosimulations:tellurium"
    ]
    assert series["solvers"]["copasi"]["Clb2"] == series["references"]["biosimulations:tellurium"]["Clb2"]
    assert len(series["labels"]) == 21
    missing = await client.get(f"/comparisons/{comparison['comparison_id']}/series", params={"report": "nope"})
    assert missing.status_code == 404
