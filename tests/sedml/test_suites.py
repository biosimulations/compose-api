"""Suites (docs/plan-sedml.md, phase 6): the seed suites parse, and a suite run submits every source, is read per
source (agreement, references), and once a run is the baseline, the next is compared with it solver by solver."""

import datetime
import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from compose_api.common.hpc.models import SlurmJob
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.sedml import suites
from compose_api.sedml.suites import Suite, load_suites
from compose_api.simulation.models import JobType
from compose_api.simulation.submission_worker import SubmissionWorker
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


async def _settled(database_service: DatabaseServiceSQL) -> None:
    """The submission worker takes the suite run's sources (its runs here are recorded, not queued)."""
    await SubmissionWorker(database_service, cast(Any, None), cast(Any, None), owner="suite-test").drain()


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
        # named, as suite.yaml files name theirs, so the counts below do not move when a solver is registered
        solvers=["copasi", "tellurium"],
    )
    monkeypatch.setattr(suites, "load_suites", lambda: {"test-suite": test_suite})

    started = (await client.post("/suites/test-suite/run", params={"environment_version": "default"})).json()
    assert started["number"] == 1
    submitting = await client.post("/suites/test-suite/run", params={"environment_version": "default"})
    assert submitting.status_code == 409  # its sources are not all submitted yet
    await _settled(database_service)
    assert [r["number"] for r in (await client.get("/suites/test-suite/runs")).json()] == [1]
    first = submitted["runs"]
    assert len(first) == 4  # two sources, two solvers each; the third source is not upstream
    assert {r[0].labels["collection"] for r in first} == {"test-suite"} and {
        r[0].labels["suite_run"] for r in first
    } == {"1"}

    running = (await client.get("/suites/test-suite/runs/1")).json()
    assert running["summary"]["running"] == 2 and running["summary"]["failed"] == 1
    # one run at a time: not while run 1's runs are going (docs/plan-webapp-admin.md, A4)
    held = await client.post("/suites/test-suite/run", params={"environment_version": "default"})
    assert held.status_code == 409 and "/suites/test-suite/runs/1" in held.json()["detail"]
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
    assert (await client.post("/suites/test-suite/run", params={"environment_version": "default"})).json()[
        "number"
    ] == 2
    await _settled(database_service)
    second = submitted["runs"][4:]
    await _finish(database_service, [r for r in second if r[0].labels["solver"] == "tellurium"], tmp_path)
    await _finish(database_service, [r for r in second if r[0].labels["solver"] == "copasi"], tmp_path, scale=1.5)
    view = (await client.get("/suites/test-suite/runs/2")).json()
    drifted = next(r for r in view["rows"] if r["source"] == "biomodels:BIOMD0000000012")
    assert drifted["drift"]["tellurium"]["close"] is True and drifted["drift"]["copasi"]["close"] is False
    assert view["summary"]["drifted"] == 2 and view["summary"]["differ"] == 2  # copasi now differs from tellurium
    assert (await client.get("/suites/test-suite/runs/9")).status_code == 404
    assert (await client.get("/suites/nope/runs")).status_code == 404


@pytest.mark.asyncio
async def test_a_stalled_run_does_not_hold_the_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    """A submitted run with a member that never finished holds its suite for `IN_FLIGHT_FOR`, then no longer."""
    from types import SimpleNamespace

    from compose_api.sedml import service, suite_runs

    now = datetime.datetime.now(datetime.UTC)
    run = SimpleNamespace(number=3, status="submitted", created_at=now)
    rows = [SimpleNamespace(members=[SimpleNamespace(simulation_id=7)])]
    db = SimpleNamespace(
        suite_runs=lambda name: _returning([run]), suite_comparisons=lambda name, number: _returning(rows)
    )
    services = SimpleNamespace(get_comparisons_db=lambda: db)
    monkeypatch.setattr(suite_runs, "get_required_database_service", lambda: services)
    monkeypatch.setattr(service, "member_statuses", lambda found: _returning({7: "running"}))
    suite = Suite(name="held", description="", sources=["biomodels:BIOMD0000000012"], solvers=["copasi"])
    assert await suite_runs.in_flight(suite) == 3
    run.created_at = (now - suite_runs.IN_FLIGHT_FOR - datetime.timedelta(minutes=1)).replace(tzinfo=None)
    assert await suite_runs.in_flight(suite) is None
    run.status = "submitting"  # still being submitted: resumed after a restart, so it holds the suite however old
    assert await suite_runs.in_flight(suite) == 3


async def _returning(value: Any) -> Any:
    return value
