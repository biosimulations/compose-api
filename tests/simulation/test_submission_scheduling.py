"""Scheduling and resumable suite runs (docs/plan-durable-submission.md, Q3 and Q4)."""

import datetime
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.sedml import suite_runs, suites
from compose_api.sedml.suites import Suite
from compose_api.simulation.models import (
    JobType,
    SimulationFileType,
    SimulationRequest,
    SimulatorVersion,
    Submission,
    SubmissionState,
)
from compose_api.simulation.scheduling import Load, SubmissionPolicy
from compose_api.simulation.submission_worker import SubmissionWorker
from tests.simulation.test_submission_worker import FakeCluster, _queue, _worker


def _candidate(n: int, queue: str = "interactive", state: SubmissionState = SubmissionState.REQUESTED) -> Submission:
    return Submission(
        simulation_id=n, experiment_id=f"e{n}", simulator_id=1, state=state, queue=queue, priority=0,
        request=SimulationRequest(request_file_path=Path("x"), simulation_file_type=SimulationFileType.OMEX,
                                  is_batch=False),
        staged_on_store=False, created_at=datetime.datetime.now(),
    )  # fmt: skip


def _ids(runs: list[Submission]) -> list[int]:
    return [r.simulation_id for r in runs]


def test_the_policy_caps_the_total_and_a_suites_share() -> None:
    policy = SubmissionPolicy(max_active=4, queue_share=0.5, max_preparing=10)
    candidates = [_candidate(1, "suite:x"), _candidate(2, "suite:x"), _candidate(3, "suite:x"), _candidate(4)]
    go, wait = policy.select(candidates, Load())
    assert _ids(go) == [1, 2, 4] and _ids(wait) == [3]  # the suite gets its half; interactive work still goes
    go, wait = policy.select([_candidate(5), _candidate(6, "suite:y")], Load(active=Counter({"interactive": 4})))
    assert go == [] and _ids(wait) == [5, 6]  # the cluster cap is reached


def test_the_policy_caps_image_preparation_not_submission() -> None:
    policy = SubmissionPolicy(max_active=100, queue_share=0.5, max_preparing=1)
    go, wait = policy.select(
        [_candidate(1), _candidate(2), _candidate(3, state=SubmissionState.SUBMITTING)], Load(preparing=0)
    )
    assert _ids(go) == [1, 3] and _ids(wait) == [2]


@pytest.fixture
def staging_dir(tmp_path: Path) -> Iterator[Path]:
    with override_settings(submission_staging_dir=str(tmp_path / "staging")):
        yield tmp_path / "staging"


@pytest.mark.asyncio
async def test_a_suite_queue_is_held_to_its_share_and_interactive_runs_go_first(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    staging_dir: Path,
) -> None:  # fmt: skip
    suite_ids = [await _queue(database_service, simulation_request, queue="suite:x", priority=-10) for _ in range(3)]
    interactive = await _queue(database_service, simulation_request)
    cluster = FakeCluster()
    with override_settings(submission_max_active_jobs=2, submission_queue_share=0.5):
        await _worker(database_service, cluster).drain()
    hpc_db = database_service.get_hpc_db()
    submitted = {
        sid for sid in [*suite_ids, interactive] if await hpc_db.get_hpcrun_by_ref(sid, JobType.SIMULATION) is not None
    }
    assert submitted == {interactive, suite_ids[0]}
    waiting = await hpc_db.get_submission(suite_ids[1])
    assert waiting is not None and waiting.state is SubmissionState.REQUESTED and waiting.attempts == 0
    load = await hpc_db.submission_load()
    assert load.active == Counter({"interactive": 1, "suite:x": 1})


@pytest.mark.asyncio
async def test_a_suite_run_resumes_from_the_source_it_had_reached(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = ["biomodels:BIOMD0000000001", "biomodels:BIOMD0000000002", "biomodels:BIOMD0000000003"]
    test_suite = Suite(name="resume-suite", description="three", sources=sources)
    monkeypatch.setattr(suites, "load_suites", lambda: {"resume-suite": test_suite})
    submitted: list[str] = []

    async def submit_source(suite: Suite, source: str, number: int) -> str | None:
        submitted.append(source)
        return "not upstream" if source.endswith("3") else None

    monkeypatch.setattr(suite_runs, "_submit_source", submit_source)
    number = await suite_runs.start(test_suite)
    comparisons = database_service.get_comparisons_db()
    # a worker that got through the first source, then went away
    taken_over = (
        "UPDATE suite_run SET next_source = 1, lease_owner = 'gone', lease_expires_at = localtimestamp - interval"  # noqa: S608
        f" '1 minute' WHERE collection = 'resume-suite' AND number = {number}"
    )
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text(taken_over))
    await SubmissionWorker(database_service, cast(Any, None), cast(Any, None), owner="w").drain()
    assert submitted == sources[1:]  # the first is not submitted again
    [run] = [r for r in await comparisons.suite_runs("resume-suite") if r.number == number]
    assert run.status == "submitted" and run.next_source == 3
    assert run.failures == {"biomodels:BIOMD0000000003": "not upstream"}
    assert run.lease_owner is None


@pytest.mark.asyncio
async def test_a_source_already_submitted_before_a_restart_is_not_submitted_again(
    database_service: DatabaseServiceSQL, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_suite = Suite(name="dedup-suite", description="two", sources=["biomodels:A1", "biomodels:B2"])
    monkeypatch.setattr(suites, "load_suites", lambda: {"dedup-suite": test_suite})
    submitted: list[str] = []

    async def submit_source(suite: Suite, source: str, number: int) -> str | None:
        submitted.append(source)
        return None

    monkeypatch.setattr(suite_runs, "_submit_source", submit_source)
    number = await suite_runs.start(test_suite)
    # A1's comparison exists (submitted), but the run's progress was not recorded before the worker died
    await database_service.get_comparisons_db().insert(
        name="A1 task", source="biomodels:A1", sedml="s.sedml", task="t", settings={},
        collection="dedup-suite", suite_run=number,
    )  # fmt: skip
    await SubmissionWorker(database_service, cast(Any, None), cast(Any, None), owner="w").drain()
    assert submitted == ["biomodels:B2"]
