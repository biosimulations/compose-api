"""The ingester against Postgres and a directory standing in for the mounted store, and the events and trace routes
that read what it stored (docs/plan-observability.md O3, O4)."""

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from compose_api.api.main import app
from compose_api.common.hpc.models import SlurmJob
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.observability.api_events import record_api_event
from compose_api.observability.identity import job_span_id
from compose_api.observability.ingest import EventIngester
from compose_api.simulation.models import HpcRun, JobType, SimulationRequest, SimulatorVersion

CORRELATION = "simulation-ingest01"


def _line(
    trace: str,
    seq: int,
    event: str,
    span: str | None,
    *,
    source: str = "job-1",
    parent: str | None = None,
    level: str = "info",
    ts: str = "2026-10-07T12:00:00.000Z",
    **payload: object,
) -> str:
    return (
        json.dumps({
            "v": 1,
            "ts": ts,
            "seq": seq,
            "source": source,
            "component": "c",
            "event": event,
            "level": level,
            "trace_id": trace,
            "span_id": span,
            "parent_span_id": parent,
            "payload": payload,
        })
        + "\n"
    )


@pytest_asyncio.fixture
async def run(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion
) -> AsyncGenerator[tuple[int, HpcRun]]:
    sim = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request, experiment_id="exp-ingest", simulator_version=simulator
    )
    hpcrun = await database_service.get_hpc_db().insert_hpcrun(
        slurmjobid=8101, job_type=JobType.SIMULATION, ref_id=sim.database_id, correlation_id=CORRELATION
    )
    yield sim.database_id, hpcrun
    await database_service.get_hpc_db().delete_hpcrun(hpcrun.database_id)
    await database_service.get_simulator_db().delete_simulation(sim.database_id)


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_ingest_tails_files_folds_spans_and_finishes_after_the_grace(
    database_service: DatabaseServiceSQL, run: tuple[int, HpcRun], tmp_path: Path
) -> None:
    simulation_id, hpcrun = run
    trace, job = hpcrun.trace_id or "", job_span_id(CORRELATION)
    task = "3" * 16
    events_dir = tmp_path / "exp-ingest" / "events"
    events_dir.mkdir(parents=True)
    clock = Clock()
    ingester = EventIngester(database_service, lambda e: tmp_path / e, grace_s=60, clock=clock)
    events_db = database_service.get_events_db()

    (events_dir / "job.jsonl").write_text(
        _line(trace, 1, "span.start", job, name="job", start_ts="2026-10-07T12:00:00.000Z")
        + _line(trace, 2, "job.start", job)
    )
    (events_dir / "engine.jsonl").write_text(
        _line(trace, 1, "span.start", task, source="n-1", parent=job, name="task", start_ts="2026-10-07T12:00:01.000Z")
        + _line(trace, 2, "tick", task, source="n-1", parent=job)
        + _line("f" * 32, 3, "foreign", task, source="n-1")  # another run's trace: skipped
        + '{"v": 1, "seq": 4, "event": "run.st'  # a writer mid-line: left for the next pass
    )
    assert await ingester.ingest_once() == 3  # job span.start, job.start, task span.start (no tick, no foreign)
    spans = await events_db.get_spans(trace)
    assert spans[task].parent_span_id == job and spans[job].end_ts is None

    with (events_dir / "engine.jsonl").open("a") as handle:  # the writer finishes its line
        handle.write('art", "source": "n-1", "trace_id": "' + trace + '", "span_id": "' + task + '"}\n')
    with (events_dir / "job.jsonl").open("a") as handle:
        handle.write(_line(trace, 3, "job.end", job, level="error", exit_code=2, wall_s=1.5))
        handle.write(
            _line(
                trace,
                4,
                "span.end",
                job,
                level="error",
                name="job",
                status="error",
                error="exit code 2",
                start_ts="2026-10-07T12:00:00.000Z",
                end_ts="2026-10-07T12:00:05.000Z",
                duration_s=5.0,
            )
        )
    assert await ingester.ingest_once() == 3
    assert await ingester.ingest_once() == 0  # nothing new; rereading is harmless anyway

    # The run ends; the task span never recorded its end. After the grace window it closes as unknown.
    await database_service.get_hpc_db().update_hpcrun_status(
        hpcrun.database_id, SlurmJob(job_id=8101, name="x", account="a", user_name="u", job_state="FAILED")
    )
    await ingester.ingest_once()
    clock.now += 61
    await ingester.ingest_once()
    spans = await events_db.get_spans(trace)
    assert spans[job].status == "error" and spans[job].duration_s == 5.0
    assert spans[task].status == "unknown" and spans[task].end_ts is not None
    assert [c for c in await events_db.ingest_candidates() if c.hpcrun_id == hpcrun.database_id] == []
    ref = await events_db.get_run_for_simulation(simulation_id)
    assert ref is not None and ref.trace_id == trace

    await record_api_event(database_service, hpcrun, "dispatch.submitted", {"slurm_job_id": 8101})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        page = (await http.get("/results/simulation/events", params={"simulation_id": simulation_id})).json()
        names = [e["event"] for e in page["events"]]
        assert page["trace_id"] == trace and page["next_cursor"] is None
        # In ingest order (files by name, each in its own order), then the API's own event.
        engine_and_job = ["span.start", "span.start", "job.start", "run.start", "job.end", "span.end"]
        assert names == [*engine_and_job, "dispatch.submitted"]
        first = await http.get("/results/simulation/events", params={"simulation_id": simulation_id, "limit": 2})
        assert first.json()["next_cursor"] == first.json()["events"][1]["cursor"]
        errors = await http.get("/results/simulation/events", params={"simulation_id": simulation_id, "level": "error"})
        assert [e["event"] for e in errors.json()["events"]] == ["job.end", "span.end"]

        tree = (await http.get("/results/simulation/trace", params={"simulation_id": simulation_id})).json()
        assert [r["span"]["name"] for r in tree["roots"]] == ["job"]
        root = tree["roots"][0]
        assert [c["span"]["name"] for c in root["children"]] == ["task"]
        assert {"job.start", "job.end", "dispatch.submitted"} <= {e["event"] for e in root["events"]}

        chrome = (await http.get("/results/simulation/trace/chrome", params={"simulation_id": simulation_id})).json()
        assert {r["name"] for r in chrome["traceEvents"] if r["ph"] == "X"} == {"job", "task"}
        assert chrome["otherData"]["simulation_id"] == str(simulation_id)

        missing = await http.get("/results/simulation/events", params={"simulation_id": 987_654_321})
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_a_run_with_no_events_directory_finishes_quietly(
    database_service: DatabaseServiceSQL, run: tuple[int, HpcRun], tmp_path: Path
) -> None:
    _, hpcrun = run
    clock = Clock()
    ingester = EventIngester(database_service, lambda e: tmp_path / e, grace_s=10, clock=clock)
    await database_service.get_hpc_db().update_hpcrun_status(
        hpcrun.database_id, SlurmJob(job_id=8101, name="x", account="a", user_name="u", job_state="COMPLETED")
    )
    assert await ingester.ingest_once() == 0
    clock.now += 11
    assert await ingester.ingest_once() == 0
    candidates = await database_service.get_events_db().ingest_candidates()
    assert hpcrun.database_id not in {c.hpcrun_id for c in candidates}
