"""The verify oracle (docs/plan-verify-oracle.md, V2 and V3): biosim's /verify output as references, and the worker
step that submits, polls and folds it into the comparison. biosim is answered from a recorded output (BIOMD0000000012
on COPASI, Tellurium and AMICI, 2026-10-22, trimmed to five time points)."""

import io
import json
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.common.gateway.models import Namespace
from compose_api.common.hpc.models import SlurmJob
from compose_api.config import get_settings, override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.sedml import suites
from compose_api.sedml.models import Tolerances
from compose_api.sedml.suites import Suite
from compose_api.sedml.verify import (
    RateBudget,
    VerifyClient,
    VerifyOutput,
    VerifyRateLimitedError,
    VerifyRejectedError,
    agrees_with,
    references_from_output,
    sanitize_archive,
    stored_output,
    verify_close,
)
from compose_api.simulation.hpc_utils import get_internal_experiment_dir
from compose_api.simulation.models import JobType, SimulationRequest, SimulatorVersion
from compose_api.simulation.submission_worker import SubmissionWorker

RESOURCES = Path(__file__).resolve().parents[1] / "fixtures" / "resources"
RECORDED_OUTPUT = RESOURCES / "verify" / "BIOMD0000000012.verify_output.json"
ARCHIVE = RESOURCES / "sources" / "BIOMD0000000012.omex"
SEDML = "BIOMD0000000012_url.sedml"
REPORT = "autogen_report_for_task1"
ORIGINS = ["biosimulators:amici:0.34.2", "biosimulators:copasi:4.45.296", "biosimulators:tellurium:2.2.10"]


def _recorded() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(RECORDED_OUTPUT.read_text())
    return data


# -- the output -- #


def test_the_recorded_output_reads_as_biosims_model() -> None:
    output = VerifyOutput.model_validate(_recorded())
    assert output.workflow_status.is_done and output.workflow_results is not None
    assert len(output.workflow_results.sims_run_info) == 3


def test_each_simulators_reports_become_a_reference_and_plots_do_not() -> None:
    references = references_from_output(VerifyOutput.model_validate(_recorded()))
    assert sorted(references) == ORIGINS
    for by_output in references.values():
        assert list(by_output) == [f"{SEDML}/{REPORT}"]  # the plot of the same series is left out
        series = by_output[f"{SEDML}/{REPORT}"]
        assert len(series) == 36 and all(len(v) == 5 for v in series.values())
        assert series["Time"][:2] == [0.0, 0.01]  # row-major: each row is one variable over time
    assert references[ORIGINS[1]][f"{SEDML}/{REPORT}"]["PX"][0] == 0.0


def test_a_series_in_an_unexpected_layout_is_dropped_not_misread() -> None:
    data = _recorded()
    data["workflow_results"]["sim_run_data"][1]["data"]["shape"] = [5, 36]
    references = references_from_output(VerifyOutput.model_validate(data))
    assert ORIGINS[1] not in references  # its one report was dropped, so it has no reference


def test_the_oracle_agrees_when_every_pair_of_simulators_is_close() -> None:
    data = _recorded()
    assert verify_close(VerifyOutput.model_validate(data)) is True
    stats = data["workflow_results"]["comparison_statistics"][f"{SEDML}/{REPORT}"]
    stats[0][2]["is_close"][3] = False  # copasi | amici on one variable
    assert verify_close(VerifyOutput.model_validate(data)) is False
    assert verify_close(VerifyOutput.model_validate(data), {f"{SEDML}/autogen_plot_for_task1"}) is True


def test_one_simulator_is_no_verdict() -> None:
    data = _recorded()
    data["workflow_results"]["sims_run_info"] = data["workflow_results"]["sims_run_info"][:1]
    assert verify_close(VerifyOutput.model_validate(data)) is None


def test_the_oracle_agrees_with_a_solver_close_to_every_one_of_its_simulators() -> None:
    """V5: which of our solvers BioSimulators sides with, from the comparison's scored pairs `solver|origin`."""
    close, far, unscored = (
        {"score": 0.1, "close": True},
        {"score": 50.0, "close": False},
        {"score": None, "close": None},
    )
    origins = ["biosimulators:copasi:4.45.296", "biosimulators:amici:0.34.2"]
    result = {
        "reports": {
            "r": {
                "labels": {
                    "A": {"copasi|tellurium": far, "copasi|biosimulators:copasi:4.45.296": close,
                          "copasi|biosimulators:amici:0.34.2": close, "tellurium|biosimulators:copasi:4.45.296": far,
                          "tellurium|biosimulators:amici:0.34.2": close, "vcell|biosimulators:amici:0.34.2": unscored,
                          "tellurium|biosimulations:copasi": close},
                    "B": {"copasi|biosimulators:copasi:4.45.296": close, "tellurium|biosimulators:amici:0.34.2": close},
                }
            }
        }
    }  # fmt: skip
    assert agrees_with(result, origins) == ["copasi"]  # tellurium is far from one; vcell has nothing scored
    assert agrees_with(result, ["biosimulators:amici:0.34.2"]) == ["copasi", "tellurium"]
    assert agrees_with(result, ["biosimulations:copasi"]) == ["tellurium"]  # only the origins asked about count
    assert agrees_with(None, origins) == [] and agrees_with(result, []) == []


def test_the_stored_output_leaves_the_series_to_the_references() -> None:
    stored = stored_output(VerifyOutput.model_validate(_recorded()))
    assert "sim_run_data" not in stored["workflow_results"]
    assert stored["workflow_results"]["comparison_statistics"]


# -- the archive (D4, amended) -- #


def _manifest_locations(content: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        manifest = z.read("manifest.xml").decode()
    return [part.split('"', 1)[0] for part in manifest.split('location="')[1:]]


def test_manifest_entries_for_missing_files_are_dropped() -> None:
    content = ARCHIVE.read_bytes()
    cleaned, dropped = sanitize_archive(content)
    assert len(dropped) == 13
    with zipfile.ZipFile(io.BytesIO(cleaned)) as z:
        names = set(z.namelist())
    kept = [loc.removeprefix("./") for loc in _manifest_locations(cleaned)]
    assert all(loc in names or loc in ("", ".", "manifest.xml") for loc in kept)
    assert f"{SEDML}" in kept
    assert sanitize_archive(cleaned) == (cleaned, [])


# -- the client and the budget -- #


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> VerifyClient:
    return VerifyClient("https://biosim.test", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_the_client_sends_the_tolerances_and_every_simulator() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={**_recorded(), "workflow_status": "PENDING", "workflow_results": None})

    out = await _client(handler).verify_omex(
        b"zip", "a.omex", ["copasi", "tellurium"], Tolerances(rel_tol=1e-6), "d", workflow_id_prefix="p-"
    )
    assert out.workflow_status == "PENDING"
    params = seen[0].url.params
    assert params.get_list("simulators") == ["copasi", "tellurium"]
    assert params["include_outputs"] == "true" and float(params["rel_tol"]) == 1e-6
    assert params["workflow_id_prefix"] == "p-"


@pytest.mark.asyncio
async def test_a_429_carries_its_retry_after_and_a_400_is_a_rejection() -> None:
    limited = _client(lambda r: httpx.Response(429, headers={"Retry-After": "17"}, json={"detail": "slow down"}))
    with pytest.raises(VerifyRateLimitedError) as e:
        await limited.get("w")
    assert e.value.retry_after == 17
    with pytest.raises(VerifyRejectedError):
        await _client(lambda r: httpx.Response(400, json={"detail": "unknown simulator"})).get("w")
    with pytest.raises(httpx.HTTPStatusError):
        await _client(lambda r: httpx.Response(503)).get("w")


def test_the_budget_holds_the_rate() -> None:
    now = [0.0]
    budget = RateBudget(per_minute=4, clock=lambda: now[0])
    assert budget.take() == 0
    assert budget.take() == pytest.approx(15)
    now[0] = 10
    assert budget.take() == pytest.approx(5)
    now[0] = 15
    assert budget.take() == 0


# -- the worker step (V3) -- #


class FakeBiosim:
    """biosim's verify endpoints: a submission, then ``polls`` answers to GET (the last is repeated)."""

    def __init__(self, polls: list[dict[str, Any]]) -> None:
        self.polls = polls
        self.posted: list[httpx.Request] = []
        self.got: list[str] = []
        self.post_answer: httpx.Response | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.posted.append(request)
            if self.post_answer is not None:
                return self.post_answer
            return httpx.Response(200, json=_pending("wf-1"))
        self.got.append(request.url.path.rsplit("/", 1)[-1])
        answer = self.polls[min(len(self.got), len(self.polls)) - 1]
        return httpx.Response(200, json=answer)

    def client(self) -> VerifyClient:
        return VerifyClient("https://biosim.test", transport=httpx.MockTransport(self.handler))


def _pending(workflow_id: str, status: str = "PENDING") -> dict[str, Any]:
    return {**_recorded(), "workflow_id": workflow_id, "workflow_status": status, "workflow_results": None}


@pytest.fixture
def mount(tmp_path: Path) -> Iterator[Path]:
    with override_settings(
        internal_mount_dir=str(tmp_path / "mount"), verify_poll_seconds=0, verify_per_minute=600
    ):  # fmt: skip
        yield tmp_path / "mount"


async def _comparison(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    tmp_path: Path,
) -> int:  # fmt: skip
    """BIOMD0000000012's task, one member whose experiment directory holds the source archive."""
    db = database_service.get_comparisons_db()
    comparison_id = await db.insert(
        name="BIOMD0000000012 task1", source="biomodels:BIOMD0000000012", sedml=SEDML, task="task1",
        settings={"tolerances": Tolerances().model_dump(), "reports": {REPORT: {"file": "r.csv", "labels": ["PX"]}},
                  "solvers": ["copasi"]},
    )  # fmt: skip
    experiment_id = f"verify-{tmp_path.name}"
    sim = await database_service.get_simulator_db().insert_simulation(simulation_request, experiment_id, simulator)
    await db.add_member(comparison_id, sim.database_id, "copasi")
    root = get_internal_experiment_dir(experiment_id, Namespace(get_settings().namespace))
    root.mkdir(parents=True)
    (root / "source.omex").write_bytes(ARCHIVE.read_bytes())
    return comparison_id


def _worker(database_service: DatabaseServiceSQL, biosim: FakeBiosim) -> SubmissionWorker:
    return SubmissionWorker(
        database_service, cast(Any, None), cast(Any, None), owner="w", verify_client=biosim.client()
    )


@pytest.mark.asyncio
async def test_a_verification_is_submitted_polled_and_folded_into_its_comparison(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    tmp_path: Path, mount: Path,
) -> None:  # fmt: skip
    comparison_id = await _comparison(database_service, simulation_request, simulator, tmp_path)
    db = database_service.get_comparisons_db()
    await db.set_result(comparison_id, "complete", {"close": True})
    verification_id = await db.insert_verification(comparison_id, ["copasi", "tellurium", "amici"], {})
    biosim = FakeBiosim([_pending("wf-1", "IN_PROGRESS"), {**_recorded(), "workflow_id": "wf-1"}])
    await _worker(database_service, biosim).drain()

    [verification] = await db.verifications(comparison_id)
    assert verification.id == verification_id
    assert (verification.state, verification.workflow_id, verification.verify_close) == ("completed", "wf-1", True)
    assert verification.lease_owner is None and verification.result is not None
    assert len(verification.settings["dropped_manifest_entries"]) == 13
    assert biosim.got == ["wf-1", "wf-1"]
    sent = biosim.posted[0]
    assert sent.url.params.get_list("simulators") == ["copasi", "tellurium", "amici"]
    assert b"BIOMD0000000012_url.sedml" in sent.content

    row = await db.get(comparison_id)
    assert row is not None
    assert sorted(r.origin for r in row.references) == ORIGINS
    assert all(list(r.reports) == [REPORT] for r in row.references)
    assert row.comparison.status == "complete" and row.comparison.result is not None
    assert row.comparison.result["references"] == ORIGINS  # scored again with them


@pytest.mark.asyncio
async def test_a_429_waits_without_spending_an_attempt(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    tmp_path: Path, mount: Path,
) -> None:  # fmt: skip
    comparison_id = await _comparison(database_service, simulation_request, simulator, tmp_path)
    db = database_service.get_comparisons_db()
    await db.insert_verification(comparison_id, ["copasi"], {})
    biosim = FakeBiosim([])
    biosim.post_answer = httpx.Response(429, headers={"Retry-After": "120"})
    await _worker(database_service, biosim).drain()
    [verification] = await db.verifications(comparison_id)
    assert (verification.state, verification.attempts, verification.lease_owner) == ("requested", 0, None)
    assert len(biosim.posted) == 1  # not again before Retry-After


@pytest.mark.asyncio
async def test_a_restart_mid_poll_resumes_the_same_workflow(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    tmp_path: Path, mount: Path, async_postgres_engine: AsyncEngine,
) -> None:  # fmt: skip
    comparison_id = await _comparison(database_service, simulation_request, simulator, tmp_path)
    db = database_service.get_comparisons_db()
    verification_id = await db.insert_verification(comparison_id, ["copasi"], {})
    # a worker submitted it, then went away holding the lease
    gone = (
        "UPDATE verification SET state = 'submitted', workflow_id = 'wf-old', submitted_at = localtimestamp,"  # noqa: S608
        f" lease_owner = 'gone', lease_expires_at = localtimestamp - interval '1 minute' WHERE id = {verification_id}"
    )
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text(gone))
    biosim = FakeBiosim([{**_recorded(), "workflow_id": "wf-old"}])
    await _worker(database_service, biosim).drain()
    [verification] = await db.verifications(comparison_id)
    assert verification.state == "completed" and biosim.posted == [] and biosim.got == ["wf-old"]


@pytest.mark.asyncio
async def test_a_workflow_biosim_failed_fails_the_verification_with_its_reason(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    tmp_path: Path, mount: Path,
) -> None:  # fmt: skip
    comparison_id = await _comparison(database_service, simulation_request, simulator, tmp_path)
    db = database_service.get_comparisons_db()
    await db.insert_verification(comparison_id, ["copasi"], {})
    failed = {**_pending("wf-1", "FAILED"), "workflow_error": "no simulator produced results"}
    await _worker(database_service, FakeBiosim([failed])).drain()
    [verification] = await db.verifications(comparison_id)
    assert (verification.state, verification.last_error) == ("failed", "no simulator produced results")
    row = await db.get(comparison_id)
    assert row is not None and row.references == []


@pytest.mark.asyncio
async def test_a_verification_past_its_deadline_fails(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    tmp_path: Path, mount: Path, async_postgres_engine: AsyncEngine,
) -> None:  # fmt: skip
    comparison_id = await _comparison(database_service, simulation_request, simulator, tmp_path)
    db = database_service.get_comparisons_db()
    verification_id = await db.insert_verification(comparison_id, ["copasi"], {})
    old = (
        "UPDATE verification SET state = 'submitted', workflow_id = 'wf-1',"  # noqa: S608
        f" submitted_at = localtimestamp - interval '7 hours' WHERE id = {verification_id}"
    )
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text(old))
    await _worker(database_service, FakeBiosim([_pending("wf-1", "IN_PROGRESS")])).drain()
    [verification] = await db.verifications(comparison_id)
    assert verification.state == "failed" and "after 21600 s" in (verification.last_error or "")


@pytest.mark.asyncio
async def test_a_comparison_whose_archive_is_gone_fails_its_verification(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    tmp_path: Path, mount: Path,
) -> None:  # fmt: skip
    comparison_id = await _comparison(database_service, simulation_request, simulator, tmp_path)
    for archive in mount.rglob("source.omex"):
        archive.unlink()
    db = database_service.get_comparisons_db()
    await db.insert_verification(comparison_id, ["copasi"], {})
    biosim = FakeBiosim([])
    await _worker(database_service, biosim).drain()
    [verification] = await db.verifications(comparison_id)
    assert verification.state == "failed" and "is gone" in (verification.last_error or "")
    assert biosim.posted == []


# -- triggers (V4) -- #


async def _finished_comparison(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    mount: Path, name: str, values: dict[str, list[float]], collection: str | None = None,
    suite_run: int | None = None, reference: list[float] | None = None, finished: bool = True,
) -> int:  # fmt: skip
    """A comparison whose members (by solver, their PX column) have completed and written their report."""
    db = database_service.get_comparisons_db()
    hpc_db = database_service.get_hpc_db()
    comparison_id = await db.insert(
        name=name, source=f"biomodels:{name}", sedml=SEDML, task="task1", collection=collection, suite_run=suite_run,
        settings={"tolerances": Tolerances().model_dump(), "reports": {REPORT: {"file": "r.csv", "labels": ["PX"]}},
                  "solvers": sorted(values)},
    )  # fmt: skip
    for solver, column in values.items():
        experiment_id = f"{name}-{solver}"
        sim = await database_service.get_simulator_db().insert_simulation(simulation_request, experiment_id, simulator)
        await db.add_member(comparison_id, sim.database_id, solver)
        root = get_internal_experiment_dir(experiment_id, Namespace(get_settings().namespace))
        root.mkdir(parents=True, exist_ok=True)
        (root / "r.csv").write_text("PX\n" + "".join(f"{v}\n" for v in column))
        (root / "source.omex").write_bytes(ARCHIVE.read_bytes())
        if finished:
            run = await hpc_db.insert_hpcrun(
                slurmjobid=sim.database_id + 70000, job_type=JobType.SIMULATION, ref_id=sim.database_id,
                correlation_id=f"verify-{sim.database_id}",
            )  # fmt: skip
            await hpc_db.update_hpcrun_status(
                run.database_id,
                SlurmJob(job_id=sim.database_id + 70000, name="x", account="a", user_name="u", job_state="COMPLETED"),
            )
    if reference is not None:
        await db.add_reference(comparison_id, "biosimulations:copasi", {REPORT: {"PX": reference}})
    return comparison_id


@pytest.mark.asyncio
async def test_verifying_a_comparison_queues_once_per_set_of_simulators(
    client: httpx.AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, mount: Path,
) -> None:  # fmt: skip
    comparison_id = await _finished_comparison(
        database_service, simulation_request, simulator, mount, "BIOMD1", {"copasi": [1, 2], "tellurium": [1, 2]}
    )
    first = await client.post(f"/comparisons/{comparison_id}/verify")
    assert first.status_code == 201
    body = first.json()
    assert body["state"] == "requested" and body["simulators"] == get_settings().verify_simulators
    again = await client.post(
        f"/comparisons/{comparison_id}/verify", content=b"null", headers={"Content-Type": "application/json"}
    )  # what the client sends for the default
    assert again.status_code == 200 and again.json()["verification_id"] == body["verification_id"]
    other = await client.post(f"/comparisons/{comparison_id}/verify", json={"simulators": ["copasi", "amici:0.34.2"]})
    assert other.status_code == 201 and other.json()["simulators"] == ["copasi", "amici:0.34.2"]
    listed = (await client.get(f"/comparisons/{comparison_id}/verifications")).json()
    assert [v["verification_id"] for v in listed] == [body["verification_id"], other.json()["verification_id"]]
    [row] = [
        v
        for v in await database_service.get_comparisons_db().verifications(comparison_id)
        if v.id == body["verification_id"]
    ]
    assert row.settings["tolerances"] == Tolerances().model_dump()  # the comparison's own (D4)

    assert (await client.post("/comparisons/999999/verify")).status_code == 404
    assert (await client.get("/comparisons/999999/verifications")).status_code == 404
    bad = await client.post(f"/comparisons/{comparison_id}/verify", json={"simulators": ["copasi; rm", "x"]})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_a_completed_verification_reads_back_with_its_references(
    client: httpx.AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, tmp_path: Path, mount: Path,
) -> None:  # fmt: skip
    comparison_id = await _comparison(database_service, simulation_request, simulator, tmp_path)
    assert (
        await client.post(f"/comparisons/{comparison_id}/verify", json={"simulators": ["copasi", "amici"]})
    ).status_code == 201
    biosim = FakeBiosim([{**_recorded(), "workflow_id": "wf-1"}])
    await _worker(database_service, biosim).drain()
    [v] = (await client.get(f"/comparisons/{comparison_id}/verifications")).json()
    assert (
        v["state"] == "completed"
        and v["verify_close"] is True
        and v["references"]
        == ["biosimulators:copasi:4.45.296", "biosimulators:tellurium:2.2.10", "biosimulators:amici:0.34.2"]
    )


@pytest.mark.asyncio
async def test_a_suite_run_verifies_its_failing_comparisons_or_all(
    client: httpx.AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, mount: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    monkeypatch.setattr(suites, "load_suites", lambda: {"oracle-suite": Suite(name="oracle-suite", description="x",
                                                                              sources=["biomodels:A1"])})  # fmt: skip
    _, number = await database_service.get_comparisons_db().new_suite_run("oracle-suite", [])
    same = {"copasi": [1.0, 2.0], "tellurium": [1.0, 2.0]}
    args = (database_service, simulation_request, simulator, mount)
    settled = await _finished_comparison(*args, "S1", same, "oracle-suite", number, reference=[1.0, 2.0])
    differ = await _finished_comparison(
        *args, "S2", {"copasi": [1.0, 2.0], "tellurium": [5.0, 9.0]}, "oracle-suite", number
    )
    unreferenced = await _finished_comparison(*args, "S3", same, "oracle-suite", number)
    await _finished_comparison(*args, "S4", same, "oracle-suite", number, finished=False)

    failing = (await client.post(f"/suites/oracle-suite/runs/{number}/verify")).json()
    assert sorted(failing["queued"]) == sorted([differ, unreferenced]) and failing["running"] == 1
    every = (await client.post(f"/suites/oracle-suite/runs/{number}/verify?which=all")).json()
    assert every["queued"] == [settled] and sorted(every["already"]) == sorted([differ, unreferenced])
    view = (await client.get(f"/suites/oracle-suite/runs/{number}")).json()
    assert view["summary"]["verifying"] == 3
    assert {r["comparison_id"]: r["verification"] for r in view["rows"]}[differ] == "requested"
    assert (await client.post("/suites/oracle-suite/runs/99/verify")).status_code == 404


@pytest.mark.asyncio
async def test_a_suites_verify_option_queues_as_its_comparisons_finish(
    client: httpx.AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, mount: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    test_suite = Suite(name="auto-suite", description="x", sources=["biomodels:A1"], verify="failing")
    monkeypatch.setattr(suites, "load_suites", lambda: {"auto-suite": test_suite})
    _, number = await database_service.get_comparisons_db().new_suite_run("auto-suite", [])
    args = (database_service, simulation_request, simulator, mount)
    same = {"copasi": [1.0, 2.0], "tellurium": [1.0, 2.0]}
    settled = await _finished_comparison(*args, "A1", same, "auto-suite", number, reference=[1.0, 2.0])
    differ = await _finished_comparison(
        *args, "A2", {"copasi": [1.0, 2.0], "tellurium": [5.0, 9.0]}, "auto-suite", number
    )
    await client.get(f"/suites/auto-suite/runs/{number}")  # reading the run scores its finished comparisons
    db = database_service.get_comparisons_db()
    assert await db.verifications(settled) == []
    assert [v.state for v in await db.verifications(differ)] == ["requested"]
    await client.get(f"/suites/auto-suite/runs/{number}")
    assert len(await db.verifications(differ)) == 1  # queued once, when it finished


@pytest.mark.asyncio
async def test_asking_again_resumes_a_verification_biosim_was_still_working_on(
    client: httpx.AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, tmp_path: Path, mount: Path, async_postgres_engine: AsyncEngine,
) -> None:  # fmt: skip
    comparison_id = await _comparison(database_service, simulation_request, simulator, tmp_path)
    db = database_service.get_comparisons_db()
    simulators = ["copasi", "tellurium"]
    timed_out = await db.insert_verification(comparison_id, simulators, {})
    biosim_failed = await db.insert_verification(comparison_id, ["amici", "copasi"], {})
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text(
            "UPDATE verification SET state = 'failed', workflow_id = 'wf-slow', workflow_status = 'IN_PROGRESS',"  # noqa: S608
            f" last_error = 'wf-slow still IN_PROGRESS after 3600 s' WHERE id = {timed_out}"
        ))  # fmt: skip
        await conn.execute(text(
            "UPDATE verification SET state = 'failed', workflow_id = 'wf-bad', workflow_status = 'FAILED',"  # noqa: S608
            f" last_error = 'Verification workflow ended with status FAILED' WHERE id = {biosim_failed}"
        ))  # fmt: skip

    resumed = await client.post(f"/comparisons/{comparison_id}/verify", json={"simulators": simulators})
    assert resumed.status_code == 200
    body = resumed.json()
    assert (body["verification_id"], body["state"], body["last_error"]) == (timed_out, "submitted", None)
    biosim = FakeBiosim([{**_recorded(), "workflow_id": "wf-slow"}])
    await _worker(database_service, biosim).drain()
    assert biosim.posted == [] and biosim.got == ["wf-slow"]  # the same workflow, polled again, not resubmitted
    [done] = [v for v in await db.verifications(comparison_id) if v.id == timed_out]
    assert done.state == "completed" and done.verify_close is True

    # a workflow biosim itself failed is not resumed: asking again submits a new one
    fresh = await client.post(f"/comparisons/{comparison_id}/verify", json={"simulators": ["amici", "copasi"]})
    assert fresh.status_code == 201 and fresh.json()["verification_id"] != biosim_failed


@pytest.mark.asyncio
async def test_member_statuses_come_from_one_query_and_match_the_per_member_view(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    mount: Path,
) -> None:  # fmt: skip
    """The suite run view reads every member's status at once (it took ~20 s for a 300-source run, a query per
    member); a finished member is its run's status and one with no run yet is `submitting`, as before."""
    from compose_api.sedml import service

    args = (database_service, simulation_request, simulator, mount)
    done = await _finished_comparison(*args, "ST1", {"copasi": [1.0], "tellurium": [1.0]})
    waiting = await _finished_comparison(*args, "ST2", {"copasi": [1.0]}, finished=False)
    db = database_service.get_comparisons_db()
    rows = [r for r in [await db.get(done), await db.get(waiting)] if r is not None]
    statuses = await service.member_statuses(rows)
    assert sorted(statuses.values()) == ["completed", "completed", "submitting"]
    for row in rows:
        batched = await service.comparison_view(row, statuses)
        alone = await service.comparison_view(row)
        assert [m.status for m in batched.members] == [m.status for m in alone.members]
    assert await database_service.get_simulator_db().get_simulation_statuses([]) == {}


@pytest.mark.asyncio
async def test_a_suite_run_counts_the_solvers_its_verifications_agree_with(
    client: httpx.AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, mount: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """V5: a completed verification's references are scored against our solvers, and the suite run says which of
    them BioSimulators agrees with, per row and in its summary; the comparison's verifications say so too."""
    monkeypatch.setattr(suites, "load_suites", lambda: {"oracle-sides": Suite(name="oracle-sides", description="x",
                                                                              sources=["biomodels:A1"])})  # fmt: skip
    db = database_service.get_comparisons_db()
    _, number = await db.new_suite_run("oracle-sides", [])
    args = (database_service, simulation_request, simulator, mount)
    differ = await _finished_comparison(
        *args, "V1", {"copasi": [1.0, 2.0], "tellurium": [5.0, 9.0]}, "oracle-sides", number
    )
    unverified = await _finished_comparison(*args, "V2", {"copasi": [1.0, 2.0]}, "oracle-sides", number)
    verification_id = await db.insert_verification(differ, ["copasi", "tellurium", "amici"], {})
    for origin in ORIGINS:  # as the worker leaves them: each simulator's series a reference
        await db.add_reference(differ, origin, {REPORT: {"PX": [1.0, 2.0]}})
    async with database_service.async_sessionmaker() as session, session.begin():
        await session.execute(
            text("UPDATE verification SET state = 'completed', verify_close = true, result = :result WHERE id = :id"),
            {"result": json.dumps(_recorded()), "id": verification_id},
        )

    view = (await client.get(f"/suites/oracle-sides/runs/{number}")).json()
    rows = {r["comparison_id"]: r for r in view["rows"]}
    assert rows[differ]["oracle_agrees_with"] == ["copasi"] and rows[differ]["verify_close"] is True
    assert rows[unverified]["oracle_agrees_with"] == [] and rows[unverified]["verification"] is None
    summary = view["summary"]
    assert (summary["oracle_agrees_with_copasi"], summary["oracle_agrees_with_tellurium"]) == (1, 0)
    assert summary["verified"] == 1 and summary["oracle_agrees"] == 1
    [v] = (await client.get(f"/comparisons/{differ}/verifications")).json()
    assert v["agrees_with"] == ["copasi"] and v["references"] == [
        "biosimulators:copasi:4.45.296", "biosimulators:tellurium:2.2.10", "biosimulators:amici:0.34.2"
    ]  # fmt: skip
