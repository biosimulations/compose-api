"""Datasets end to end without SLURM: ``artifact.written`` events in a run's event files, through the ingester, to
the dataset routes, with the read policy applied (docs/plan-observability.md O5-O8)."""

import hashlib
import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from compose_api.api.main import app
from compose_api.api.routers import datasets as datasets_router
from compose_api.authorization import get_caller
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.observability.identity import job_span_id
from compose_api.observability.ingest import EventIngester
from compose_api.simulation.models import JobType, SimulationRequest, SimulatorVersion, Visibility
from tests.api.test_authorization import ALICE, BOB

CORRELATION = "simulation-datasets1"
CSV = b"time,a\n0,1\n1,2\n"
MANIFEST = '{"vcell_fenics": {"status": "completed"}}'
CHUNK = bytes(range(64))


def _artifact(trace: str, seq: int, component: str, **payload: object) -> str:
    record = {"v": 1, "ts": "2026-10-07T12:00:00.000Z", "seq": seq, "source": component, "component": component}
    record.update(event="artifact.written", level="info", trace_id=trace, span_id=job_span_id(CORRELATION))
    return json.dumps({**record, "payload": payload}) + "\n"


@pytest_asyncio.fixture
async def ingested(
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[tuple[int, Path]]:
    sim_db, hpc_db = database_service.get_simulator_db(), database_service.get_hpc_db()
    sim = await sim_db.insert_simulation(
        sim_request=simulation_request,
        experiment_id="exp-datasets",
        simulator_version=simulator,
        owner_sub=ALICE.subject,
        visibility=Visibility.PRIVATE,
    )
    run = await hpc_db.insert_hpcrun(
        slurmjobid=9101, job_type=JobType.SIMULATION, ref_id=sim.database_id, correlation_id=CORRELATION
    )
    experiment = tmp_path / "exp-datasets"
    (experiment / "output").mkdir(parents=True)
    (experiment / "output" / "a.csv").write_bytes(CSV)
    bundle = experiment / "output" / "run.fenics"  # a results bundle: a zarr store, one dataset read file by file
    (bundle / "u").mkdir(parents=True)
    (bundle / ".zattrs").write_text(MANIFEST)
    (bundle / "u" / "0.0").write_bytes(CHUNK)
    (bundle / "escape").symlink_to(tmp_path)  # leaves the bundle: must never be served
    (experiment / "events").mkdir()
    trace = run.trace_id or ""
    digest = hashlib.sha256(CSV).hexdigest()
    (experiment / "events" / "job.jsonl").write_text(
        _artifact(trace, 1, "compose_api.job", uri="output/a.csv", bytes=len(CSV), sha256=digest)
        + _artifact(trace, 2, "compose_api.job", uri="output/gone.csv", bytes=3)
        + _artifact(trace, 3, "compose_api.job", uri="output/run.fenics", bytes=len(MANIFEST) + len(CHUNK))
    )
    (experiment / "events" / "engine.jsonl").write_text(
        _artifact(trace, 1, "process_bigraph", uri="/experiment/output/a.csv", kind="species", name="Species")
        + _artifact(trace, 2, "process_bigraph", uri="/etc/passwd")  # outside the experiment: never registered
    )
    await EventIngester(database_service, lambda e: tmp_path / e).ingest_once()
    monkeypatch.setattr(datasets_router, "get_internal_experiment_dir", lambda e, ns: tmp_path / e)
    yield sim.database_id, experiment
    app.dependency_overrides.pop(get_caller, None)
    await hpc_db.delete_hpcrun(run.database_id)
    await sim_db.delete_simulation(sim.database_id)


def _as(caller: object) -> None:
    async def override() -> object:
        return caller

    app.dependency_overrides[get_caller] = override


@pytest.mark.asyncio
async def test_datasets_are_registered_listed_and_served(ingested: tuple[int, Path]) -> None:
    simulation_id, _ = ingested
    _as(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        page = (await http.get("/datasets", params={"simulation_id": simulation_id})).json()
        by_path = {d["path"]: d for d in page["datasets"]}
        assert set(by_path) == {"output/a.csv", "output/gone.csv", "output/run.fenics"} and page["total"] == 3
        a = by_path["output/a.csv"]
        assert (a["kind"], a["display_name"], a["origin"]) == ("species", "Species", "event")  # the engine's wins
        assert a["size_bytes"] == len(CSV) and a["sha256"] == hashlib.sha256(CSV).hexdigest()  # the manifest's
        assert a["media_type"] == "text/csv"

        assert (await http.get(f"/datasets/{a['id']}")).json()["path"] == "output/a.csv"
        content = await http.get(f"/datasets/{a['id']}/content")
        assert content.status_code == 200 and content.content == CSV
        assert 'filename="a.csv"' in content.headers["content-disposition"]
        part = await http.get(f"/datasets/{a['id']}/content", headers={"Range": "bytes=0-3"})
        assert part.status_code == 206 and part.content == CSV[:4]

        gone = by_path["output/gone.csv"]
        assert (await http.get(f"/datasets/{gone['id']}/content")).status_code == 404
        assert (await http.get(f"/datasets/{gone['id']}")).json()["available"] is False
        missing = await http.get("/datasets", params={"simulation_id": simulation_id, "available": False})
        assert [d["path"] for d in missing.json()["datasets"]] == ["output/gone.csv"]

        tables = await http.get("/datasets", params={"simulation_id": simulation_id, "q": "a.c", "limit": 1})
        assert tables.json()["total"] == 1 and tables.json()["next_offset"] is None


@pytest.mark.asyncio
async def test_a_private_simulations_datasets_are_not_found_by_others(ingested: tuple[int, Path]) -> None:
    simulation_id, _ = ingested
    _as(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        dataset_id = (await http.get("/datasets", params={"simulation_id": simulation_id})).json()["datasets"][0]["id"]
        for caller in (None, BOB):
            _as(caller)
            assert (await http.get("/datasets", params={"simulation_id": simulation_id})).status_code == 404
            assert simulation_id not in {d["simulation_id"] for d in (await http.get("/datasets")).json()["datasets"]}
            assert (await http.get(f"/datasets/{dataset_id}")).status_code == 404
            assert (await http.get(f"/datasets/{dataset_id}/content")).status_code == 404


def test_content_paths_cannot_leave_the_experiment(tmp_path: Path) -> None:
    experiment = tmp_path / "exp"
    (experiment / "output").mkdir(parents=True)
    (tmp_path / "secret").write_text("x")
    (experiment / "output" / "link").symlink_to(tmp_path / "secret")
    resolve = datasets_router.resolve_content_path
    assert resolve(experiment, "output/a.csv") == (experiment / "output" / "a.csv").resolve()
    assert resolve(experiment, "../secret") is None
    assert resolve(experiment, "output/link") is None


@pytest.mark.asyncio
async def test_a_bundle_is_one_dataset_read_file_by_file(ingested: tuple[int, Path]) -> None:
    simulation_id, _ = ingested
    _as(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        page = (await http.get("/datasets", params={"simulation_id": simulation_id, "kind": "results-bundle"})).json()
        (bundle,) = page["datasets"]
        assert (bundle["path"], bundle["media_type"]) == (
            "output/run.fenics",
            "application/vnd.vcell.results-bundle+zarr",
        )
        files = f"/datasets/{bundle['id']}/files"

        manifest = await http.get(f"{files}/.zattrs")
        assert manifest.status_code == 200 and manifest.text == MANIFEST
        assert manifest.headers["cache-control"] == "no-cache" and manifest.headers["etag"]

        ranged = await http.get(f"{files}/u/0.0", headers={"Range": "bytes=8-15"})
        assert ranged.status_code == 206 and ranged.content == CHUNK[8:16]

        for missing in ("u/9.9", "u", "escape/exp-datasets/output/a.csv", "../a.csv"):
            assert (await http.get(f"{files}/{missing}")).status_code == 404, missing

        content = await http.get(f"/datasets/{bundle['id']}/content")
        assert content.status_code == 409
        # A directory is not a missing file: it stays available.
        assert (await http.get(f"/datasets/{bundle['id']}")).json()["available"] is True


@pytest.mark.asyncio
async def test_a_plain_files_dataset_has_no_files(ingested: tuple[int, Path]) -> None:
    simulation_id, _ = ingested
    _as(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        page = (await http.get("/datasets", params={"simulation_id": simulation_id, "kind": "species"})).json()
        (csv,) = page["datasets"]
        assert (await http.get(f"/datasets/{csv['id']}/files/a.csv")).status_code == 404


@pytest.mark.asyncio
async def test_a_bundles_files_are_not_found_by_others(ingested: tuple[int, Path]) -> None:
    simulation_id, _ = ingested
    _as(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        page = (await http.get("/datasets", params={"simulation_id": simulation_id, "kind": "results-bundle"})).json()
        bundle_id = page["datasets"][0]["id"]
        _as(BOB)
        assert (await http.get(f"/datasets/{bundle_id}/files/.zattrs")).status_code == 404
