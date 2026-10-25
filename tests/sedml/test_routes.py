"""/sedml/preview, /sedml/run and /comparisons (docs/plan-sedml.md, phase 3), with process-bigraph-lang's real
translation (`make pblang`) and a real database. Submission is replaced by recording the simulation, and each run's
end by writing its report where the job would: the comparison is then computed from those CSVs."""

import io
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from compose_api.common.hpc.models import SlurmJob
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.models import JobType
from tests.sedml.conftest import needs_translator

SEDML = Path(__file__).resolve().parents[1] / "fixtures" / "resources" / "sedml"
SOURCE = SEDML / "Ciliberto2003.source.omex"

pytestmark = needs_translator


def _upload() -> dict[str, tuple[str, bytes, str]]:
    return {"archive": ("Ciliberto2003.omex", SOURCE.read_bytes(), "application/zip")}


@pytest.mark.asyncio
async def test_preview_translates_without_running(client: httpx.AsyncClient, submitted: dict[str, Any]) -> None:
    response = await client.post("/sedml/preview", files=_upload())
    assert response.status_code == 200, response.text
    body = response.json()
    (task,) = body["tasks"]
    assert (task["task"], task["solvers"], task["refused"], task["reports"]) == (
        "task_1",
        ["copasi", "tellurium", "vcell"],
        [],
        ["report"],
    )
    assert "TimeCourseSolver at ?" in task["template"]
    assert [(f["code"], f["solver"]) for f in body["findings"]] == [("X405", "copasi")]  # CVODE asked, LSODA runs
    assert submitted["runs"] == []
    assert (
        await client.post("/sedml/preview", files={"archive": ("x.omex", b"not a zip", "application/zip")})
    ).status_code == 400
    assert (await client.post("/sedml/preview", files=_upload(), params={"solvers": ["nope"]})).status_code == 400


@pytest.mark.asyncio
async def test_run_makes_one_labelled_run_per_solver_and_a_comparison(
    client: httpx.AsyncClient, submitted: dict[str, Any], database_service: DatabaseServiceSQL, tmp_path: Path
) -> None:
    response = await client.post("/sedml/run", files=_upload(), params={"tags": ["demo"], "description": "Ciliberto"})
    assert response.status_code == 200, response.text
    (comparison,) = response.json()["comparisons"]
    cid = comparison["comparison_id"]
    assert comparison["status"] == "running" and comparison["task"] == "task_1"
    assert sorted(m["solver"] for m in comparison["members"]) == ["copasi", "tellurium", "vcell"]
    assert comparison["settings"]["reports"]["report"]["file"] == "output/reports/simulation_1/report.csv"

    runs = submitted["runs"]
    assert len(runs) == 3
    for request, _sim_id, _exp in runs:
        assert request.labels["comparison"] == str(cid) and request.labels["sedml_task"] == "task_1"
        assert request.labels["source"] == "upload" and request.labels["environment"] == "registry_env"
        assert request.tags == ["demo"] and request.description == "Ciliberto"
        assert request.source_file_path is not None and request.source_file_path.read_bytes() == SOURCE.read_bytes()
        with zipfile.ZipFile(request.request_file_path) as z:
            assert sorted(z.namelist()) == ["BIOMD0000000297_url.changed.xml", "task_1.pbg", "task_1.pblang"]
    assert {r[0].labels["solver"] for r in runs} == {"copasi", "tellurium", "vcell"}

    # each run completes, writing its report where the job would
    hpc_db = database_service.get_hpc_db()
    for n, (request, sim_id, experiment_id) in enumerate(runs):
        run = await hpc_db.insert_hpcrun(
            slurmjobid=9500 + n, job_type=JobType.SIMULATION, ref_id=sim_id, correlation_id=f"sedml-{cid}-{n}"
        )
        await hpc_db.update_hpcrun_status(
            run.database_id, SlurmJob(job_id=9500 + n, name="x", account="a", user_name="u", job_state="COMPLETED")
        )
        drift = 0.0 if request.labels["solver"] == "copasi" else 1e-9
        report = tmp_path / "mount" / "test" / "sims" / f"experiment-{experiment_id}" / "output" / "reports"
        (report / "simulation_1").mkdir(parents=True)
        labels = comparison["settings"]["reports"]["report"]["labels"]
        rows = [",".join(f'"{x}"' for x in labels)] + [
            ",".join(str(t + i + drift) for i in range(len(labels))) for t in (0.0, 1.0, 2.0)
        ]
        (report / "simulation_1" / "report.csv").write_text("\n".join(rows) + "\n")

    done = (await client.get(f"/comparisons/{cid}")).json()
    assert done["status"] == "complete" and done["close"] is True, done
    assert done["result"]["reports"]["report"]["labels"]["Total Swe1"]["copasi|tellurium"]["close"] is True
    listed = (await client.get("/comparisons", params={"source": "upload:Ciliberto2003.omex"})).json()
    assert [c["comparison_id"] for c in listed["comparisons"]][:1] == [cid]
    assert (await client.get("/comparisons/987654")).status_code == 404
    found = (await client.get("/simulations", params={"label": f"comparison:{cid}"})).json()
    assert found["total"] == 3


@pytest.mark.asyncio
async def test_a_task_no_solver_accepts_is_a_400(client: httpx.AsyncClient, submitted: dict[str, Any]) -> None:
    text = zipfile.ZipFile(SOURCE).read("simulation_1.sedml").decode().replace('initialTime="0"', 'initialTime="1"')
    buffer = io.BytesIO()
    with zipfile.ZipFile(SOURCE) as src, zipfile.ZipFile(buffer, "w") as out:
        for name in src.namelist():
            out.writestr(name, text if name == "simulation_1.sedml" else src.read(name))
    response = await client.post("/sedml/run", files={"archive": ("late.omex", buffer.getvalue(), "application/zip")})
    assert response.status_code == 400
    assert {f["code"] for f in response.json()["detail"]["findings"]} >= {"X402"}
    assert submitted["runs"] == []
