"""Suites (docs/plan-sedml.md, phase 6): the seed suites parse, and a suite run submits every source, is read per
source (agreement, references), and once a run is the baseline, the next is compared with it solver by solver."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from compose_api.common.hpc.models import SlurmJob
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.sedml import suite_runs, suites
from compose_api.sedml.suites import Suite, load_suites
from compose_api.simulation.models import JobType
from tests.sedml.conftest import PROJECT, needs_translator


def test_the_seed_suites_parse() -> None:
    found = load_suites()
    assert {"biomodels-ode-sample", "biosimulations-reference", "smoke"} <= set(found)
    assert len(found["smoke"].sources) == 2
    assert len(found["biomodels-ode-sample"].sources) == 20
    assert all(s.startswith("biosimulations:") for s in found["biosimulations-reference"].sources)
    with pytest.raises(ValueError):
        Suite(name="x", description="", sources=["github:nope"])


async def _finish(database_service: DatabaseServiceSQL, runs: list[Any], tmp_path: Path, scale: float = 1.0) -> None:
    """Every recorded run completes, writing its reports where the job would (each label's values: its position)."""
    hpc_db = database_service.get_hpc_db()
    for request, sim_id, experiment_id in runs:
        run = await hpc_db.insert_hpcrun(
            slurmjobid=sim_id + 90000, job_type=JobType.SIMULATION, ref_id=sim_id, correlation_id=f"suite-{sim_id}"
        )
        await hpc_db.update_hpcrun_status(
            run.database_id,
            SlurmJob(job_id=sim_id + 90000, name="x", account="a", user_name="u", job_state="COMPLETED"),
        )
        comparison = await database_service.get_comparisons_db().get(int(request.labels["comparison"]))
        assert comparison is not None
        for info in comparison.comparison.settings["reports"].values():
            path = tmp_path / "mount" / "test" / "sims" / f"experiment-{experiment_id}" / str(info["file"])
            path.parent.mkdir(parents=True, exist_ok=True)
            labels = info["labels"]
            rows = [",".join(json.dumps(x) for x in labels)] + [
                ",".join(repr(scale * (t + i)) for i in range(len(labels))) for t in range(3)
            ]
            path.write_text("\n".join(rows) + "\n")


async def _settled() -> None:
    while suite_runs._running:
        await asyncio.gather(*list(suite_runs._running))


@needs_translator
@pytest.mark.asyncio
async def test_a_suite_run_and_its_drift_from_the_baseline(
    client: httpx.AsyncClient,
    submitted: dict[str, Any],
    recorded_sources: list[str],
    database_service: DatabaseServiceSQL,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_suite = Suite(
        name="test-suite",
        description="two sources",
        sources=["biomodels:BIOMD0000000012", f"biosimulations:{PROJECT}", "biomodels:BIOMD9999999999"],
        expected=[],
    )
    monkeypatch.setattr(suites, "load_suites", lambda: {"test-suite": test_suite})

    started = (await client.post("/suites/test-suite/run")).json()
    assert started["number"] == 1
    await _settled()
    assert [r["number"] for r in (await client.get("/suites/test-suite/runs")).json()] == [1]
    first = submitted["runs"]
    assert len(first) == 4  # two sources, two solvers each; the third source is not upstream
    assert {r[0].labels["collection"] for r in first} == {"test-suite"} and {
        r[0].labels["suite_run"] for r in first
    } == {"1"}

    running = (await client.get("/suites/test-suite/runs/1")).json()
    assert running["summary"]["running"] == 2 and running["summary"]["failed"] == 1
    failed = next(r for r in running["rows"] if r["failure"])
    assert failed["source"] == "biomodels:BIOMD9999999999"

    await _finish(database_service, first, tmp_path)
    done = (await client.get("/suites/test-suite/runs/1")).json()
    assert done["summary"]["agree"] == 2 and done["summary"]["running"] == 0
    project_row = next(r for r in done["rows"] if r["source"] == f"biosimulations:{PROJECT}")
    assert project_row["close"] is True and project_row["close_to_references"] is False  # made-up values
    assert all(r["drift"] is None for r in done["rows"])  # no baseline yet

    # run 1 accepted as the baseline; run 2's COPASI results drift, Tellurium's do not
    monkeypatch.setattr(test_suite, "baseline", 1)
    assert (await client.post("/suites/test-suite/run")).json()["number"] == 2
    await _settled()
    second = submitted["runs"][4:]
    await _finish(database_service, [r for r in second if r[0].labels["solver"] == "tellurium"], tmp_path)
    await _finish(database_service, [r for r in second if r[0].labels["solver"] == "copasi"], tmp_path, scale=1.5)
    view = (await client.get("/suites/test-suite/runs/2")).json()
    drifted = next(r for r in view["rows"] if r["source"] == "biomodels:BIOMD0000000012")
    assert drifted["drift"]["tellurium"]["close"] is True and drifted["drift"]["copasi"]["close"] is False
    assert view["summary"]["drifted"] == 2 and view["summary"]["differ"] == 2  # copasi now differs from tellurium
    assert (await client.get("/suites/test-suite/runs/9")).status_code == 404
    assert (await client.get("/suites/nope/runs")).status_code == 404
