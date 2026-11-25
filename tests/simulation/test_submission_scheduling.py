"""Scheduling and resumable suite runs (docs/plan-durable-submission.md, Q3 and Q4)."""

import asyncio
import datetime
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.db.tables.hpc_tables import JobStatusDB, ORMHpcRun
from compose_api.sedml import suite_runs, suites
from compose_api.sedml.suites import Suite
from compose_api.simulation.models import (
    JobType,
    Ownership,
    SimulationFileType,
    SimulationRequest,
    SimulatorVersion,
    Submission,
    SubmissionState,
)
from compose_api.simulation.scheduling import Load, SubmissionPolicy
from compose_api.simulation.submission_worker import SubmissionWorker
from tests.simulation.test_submission_worker import FakeCluster, _queue, _set, _worker


def _candidate(
    n: int, queue: str = "interactive", state: SubmissionState = SubmissionState.REQUESTED,
    requested_by: str | None = None,
) -> Submission:  # fmt: skip
    return Submission(
        simulation_id=n, experiment_id=f"e{n}", simulator_id=1, state=state, queue=queue, priority=0,
        request=SimulationRequest(request_file_path=Path("x"), simulation_file_type=SimulationFileType.OMEX,
                                  is_batch=False),
        staged_on_store=False, created_at=datetime.datetime.now(), requested_by=requested_by,
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


def test_the_policy_caps_one_requesters_interactive_runs_and_counts_anonymous_runs_as_one() -> None:
    policy = SubmissionPolicy(max_active=100, queue_share=0.5, max_preparing=100, max_active_per_requester=2)
    candidates = [
        _candidate(1, requested_by="a"), _candidate(2, requested_by="a"), _candidate(3, requested_by="b"),
        _candidate(4), _candidate(5), _candidate(6), _candidate(7, "suite:x", requested_by="a"),
    ]  # fmt: skip
    go, wait = policy.select(candidates, Load(active_by_requester=Counter({"a": 1})))
    # a had one running: one more goes. Anonymous runs share one allowance. A suite's runs aren't counted per requester.
    assert _ids(go) == [1, 3, 4, 5, 7] and _ids(wait) == [2, 6]


def test_a_run_already_submitting_is_not_held_back_by_the_counts_it_is_in() -> None:
    policy = SubmissionPolicy(max_active=2, queue_share=0.5, max_preparing=8, max_active_per_requester=1)
    load = Load(active=Counter({"interactive": 2}), active_by_requester=Counter({"a": 2}))
    resuming = [_candidate(n, state=SubmissionState.SUBMITTING, requested_by="a") for n in (1, 2)]
    go, wait = policy.select([*resuming, _candidate(3, requested_by="b")], load)
    # the two put the counts at their caps themselves: they resume, and aren't counted again; a new run still waits
    assert _ids(go) == [1, 2] and _ids(wait) == [3]


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
@pytest.mark.parametrize("cap", [1, 3])
@pytest.mark.parametrize(
    ("backlog_by", "later_by"),
    [("student-a", ["student-b", None]), (None, ["student-b", "student-c"])],
    ids=["a-signed-in-backlog", "an-anonymous-backlog"],
)
async def test_a_requester_at_its_cap_does_not_starve_the_runs_queued_after_it(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    staging_dir: Path, backlog_by: str | None, later_by: list[str | None], cap: int,
) -> None:  # fmt: skip
    """One requester's backlog, queued first, must not hold back everyone queued after it.

    A claim takes the oldest due rows. If a requester at its cap were only put back, its rows would come due again,
    still the oldest, and fill every claim: here a 0 s deferral and a claim of two stand in for production's 10 s
    deferral and a backlog of more than two claims' worth. Without the claim leaving the capped requester out, only
    the backlog's first run is submitted. With a cap of 3 the backlog also reaches cap - 1 with more due rows than a
    claim takes: two are claimed, one goes, one is put back, and the next claim still reaches the runs queued after it.
    Anonymous runs are one requester, both as the backlog and queued after one.
    """
    backlog = [await _queue(database_service, simulation_request, requested_by=backlog_by) for _ in range(cap + 2)]
    later = [await _queue(database_service, simulation_request, requested_by=by) for by in later_by]
    suite = await _queue(database_service, simulation_request, queue="suite:x", requested_by=backlog_by)
    cluster = FakeCluster()
    with override_settings(
        submission_max_active_per_requester=cap, submission_worker_concurrency=2, submission_defer_seconds=0
    ):
        worker = _worker(database_service, cluster)
        await worker.drain()
        assert await worker.run_once() == []  # nothing more goes: the backlog's requester is at its cap
    hpc_db = database_service.get_hpc_db()
    submitted = {
        sid for sid in [*backlog, *later, suite] if await hpc_db.get_hpcrun_by_ref(sid, JobType.SIMULATION) is not None
    }
    # the backlog's first `cap` runs, each run queued after it, and the suite's run, which the per-requester cap
    # doesn't cover
    assert submitted == {*backlog[:cap], *later, suite}
    for sid in backlog[cap:]:
        waiting = await hpc_db.get_submission(sid)
        assert waiting is not None and waiting.state is SubmissionState.REQUESTED and waiting.attempts == 0
    load = await hpc_db.submission_load()
    assert load.active_by_requester == Counter([backlog_by] * cap + later_by)
    assert load.active == Counter({"interactive": cap + len(later_by), "suite:x": 1})


@pytest.mark.asyncio
async def test_runs_waiting_to_retry_their_submit_are_resumed_at_the_cap(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    """An SSH outage at sbatch: a requester's runs wait to retry in `submitting`, and they alone fill its cap.

    They are counted, so they must not count themselves out: once the backoff has passed they are resumed, while the
    requester's next run still waits for a place. Holding them back by their own count would leave them, and that
    requester, stuck for good: nothing else retries or fails a row nobody claims.
    """
    runs = [await _queue(database_service, simulation_request, requested_by="student-a") for _ in range(3)]
    cluster = FakeCluster()
    cluster.fail_submits = 2
    hpc_db = database_service.get_hpc_db()
    with override_settings(submission_max_active_per_requester=2, submission_worker_concurrency=2):
        worker = _worker(database_service, cluster)
        await worker.drain()
        for sid in runs[:2]:
            waiting = await hpc_db.get_submission(sid)
            assert waiting is not None and waiting.state is SubmissionState.SUBMITTING and waiting.attempts == 1
        async with async_postgres_engine.begin() as conn:  # the backoff passes
            await conn.execute(text("UPDATE submission SET next_attempt_at = localtimestamp - interval '1 second'"))
        await worker.drain()
    submitted = [await hpc_db.get_hpcrun_by_ref(sid, JobType.SIMULATION) is not None for sid in runs]
    assert submitted == [True, True, False]
    third = await hpc_db.get_submission(runs[2])
    assert third is not None and third.state is SubmissionState.REQUESTED


@pytest.mark.asyncio
async def test_a_requesters_finished_run_frees_its_place(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    first, second = [await _queue(database_service, simulation_request, requested_by="student-a") for _ in range(2)]
    hpc_db = database_service.get_hpc_db()
    with override_settings(submission_max_active_per_requester=1, submission_defer_seconds=0):
        worker = _worker(database_service, FakeCluster())
        await worker.drain()
        assert await hpc_db.get_hpcrun_by_ref(second, JobType.SIMULATION) is None  # its requester is at the cap
        async with async_postgres_engine.begin() as conn:  # the first run's job ends (the job monitor's part)
            await conn.execute(
                update(ORMHpcRun).where(ORMHpcRun.simulation_id == first).values(status=JobStatusDB.COMPLETED)
            )
        await worker.drain()
    assert await hpc_db.get_hpcrun_by_ref(second, JobType.SIMULATION) is not None


@pytest.mark.asyncio
async def test_a_signed_in_runs_requester_is_its_owner_when_not_given(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    staging_dir: Path,
) -> None:  # fmt: skip
    """/sedml/run, /sources and /curated pass the run's owner but not `requested_by`: it is who the run counts against,
    not the anonymous allowance."""
    owned = await _queue(database_service, simulation_request, ownership=Ownership(owner_sub="student-a"))
    anonymous = await _queue(database_service, simulation_request)
    hpc_db = database_service.get_hpc_db()
    requesters = [(await hpc_db.get_submission(sid)) for sid in (owned, anonymous)]
    assert [s.requested_by if s is not None else "missing" for s in requesters] == ["student-a", None]


async def _hold(engine: AsyncEngine, simulation_id: int, owner: str = "another-worker") -> None:
    """A run a worker holds on its way to sbatch: making its image ready, under a live lease."""
    await _set(
        engine, simulation_id,
        f"state = 'preparing', lease_owner = '{owner}', lease_expires_at = localtimestamp + interval '5 minutes'",
    )  # fmt: skip


@pytest.mark.asyncio
async def test_a_run_a_worker_holds_counts_toward_its_requesters_cap_in_the_claim(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    """Cap 1. A named requester and the anonymous one each have a run held (not yet submitting): neither gets another.
    Another requester does, and so does an anonymous run already submitting, which is counted already."""
    hpc_db = database_service.get_hpc_db()
    held_anonymous = await _queue(database_service, simulation_request)
    held_named = await _queue(database_service, simulation_request, requested_by="student-a")
    for sid in (held_anonymous, held_named):
        await _hold(async_postgres_engine, sid)
    anonymous = await _queue(database_service, simulation_request)
    named = await _queue(database_service, simulation_request, requested_by="student-a")
    other = await _queue(database_service, simulation_request, requested_by="student-b")
    resuming = await _queue(database_service, simulation_request)
    await _set(async_postgres_engine, resuming, "state = 'submitting'")
    claimed = await hpc_db.claim_submissions(owner="w", lease_seconds=120, limit=10, requester_cap=1)
    assert sorted(c.simulation_id for c in claimed) == sorted([other, resuming])
    assert anonymous not in {c.simulation_id for c in claimed} and named not in {c.simulation_id for c in claimed}


class _CommitAfterFirstStatement:
    """A session that lets another transaction commit right after its first statement: what a worker moving a run on
    at that moment looks like to a reader at READ COMMITTED."""

    def __init__(self, inner: Any, commit: Any) -> None:
        self._inner, self._commit, self._statements = inner, commit, 0

    async def __aenter__(self) -> "_CommitAfterFirstStatement":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> Any:
        return await self._inner.__aexit__(*exc)

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        result = await self._inner.execute(statement, *args, **kwargs)
        self._statements += 1
        if self._statements == 1:
            await self._commit()
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("moves_on_mid_read", [False, True])
async def test_a_held_run_counts_toward_its_requesters_cap_in_select_once(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path, monkeypatch: pytest.MonkeyPatch, moves_on_mid_read: bool,
) -> None:  # fmt: skip
    """Cap 2. The requester's first run is held (preparing); the claim takes its next two. The load must count the
    held run, so only one more goes; and counted once even when it moves on to submitting while the load is read,
    which one statement (one snapshot) guarantees: read in two, it was in neither, and both went."""
    hpc_db = database_service.get_hpc_db()
    first, *rest = [await _queue(database_service, simulation_request, requested_by="student-a") for _ in range(3)]
    await _hold(async_postgres_engine, first, owner="w")
    claimed = await hpc_db.claim_submissions(
        owner="w", lease_seconds=120, limit=2, exclude=frozenset({first}), requester_cap=2
    )
    assert sorted(c.simulation_id for c in claimed) == sorted(rest)

    async def moves_on() -> None:
        await _set(async_postgres_engine, first, "state = 'submitting'")

    if moves_on_mid_read:
        session_maker = hpc_db.async_session_maker  # type: ignore[attr-defined]
        monkeypatch.setattr(
            hpc_db, "async_session_maker", lambda: _CommitAfterFirstStatement(session_maker(), moves_on)
        )
    load = await hpc_db.submission_load(exclude=frozenset(c.simulation_id for c in claimed))
    monkeypatch.undo()
    policy = SubmissionPolicy(max_active=100, queue_share=0.5, max_preparing=100, max_active_per_requester=2)
    go, _ = policy.select(claimed, load)
    assert load.active_by_requester == Counter({"student-a": 1}) and len(go) == 1


class _ImageNeverReady(FakeCluster):
    """The image pull doesn't finish: runs stay `preparing` until the worker is closed (a restart)."""

    async def download_container(self, remote_container_image: Any) -> None:
        await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_runs_given_back_while_preparing_are_resumed_by_the_next_worker(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion,
    staging_dir: Path,
) -> None:  # fmt: skip
    """A restart while as many runs as max_preparing wait on their image: they are given back still `preparing`. The
    next worker claims them, and their fresh leases must not count them out of max_preparing, or they wait forever."""
    runs = [await _queue(database_service, simulation_request) for _ in range(8)]
    hpc_db = database_service.get_hpc_db()
    first = _worker(database_service, _ImageNeverReady(), owner="first")
    assert sorted(await first.run_once()) == sorted(runs)

    async def all_preparing() -> bool:
        states = [await hpc_db.get_submission(sid) for sid in runs]
        return all(s is not None and s.state is SubmissionState.PREPARING for s in states)

    async with asyncio.timeout(10):
        while not await all_preparing():
            await asyncio.sleep(0.05)
    await first.close()  # the restart gives them back
    with override_settings(submission_defer_seconds=0):
        await _worker(database_service, FakeCluster(), owner="second").drain()
    assert [await hpc_db.get_hpcrun_by_ref(sid, JobType.SIMULATION) is not None for sid in runs] == [True] * 8


@pytest.mark.asyncio
async def test_a_submitting_run_behind_a_backlog_that_waits_is_still_claimed(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staging_dir: Path,
) -> None:  # fmt: skip
    """The overall cap is held by a suite run waiting to retry its sbatch, behind a claim's worth of interactive runs
    that the cap puts back. Claimed after them, it never would be, and the cap would never free: it goes first."""
    suite = await _queue(database_service, simulation_request, queue="suite:x", priority=-10)
    await _set(
        async_postgres_engine, suite,
        "state = 'submitting', attempts = 1, next_attempt_at = localtimestamp - interval '1 second'",
    )  # fmt: skip
    for _ in range(2):
        await _queue(database_service, simulation_request)
    with override_settings(submission_max_active_jobs=1, submission_worker_concurrency=2, submission_defer_seconds=0):
        await _worker(database_service, FakeCluster()).drain()
    assert await database_service.get_hpc_db().get_hpcrun_by_ref(suite, JobType.SIMULATION) is not None


@pytest.mark.asyncio
async def test_a_suite_run_resumes_from_the_source_it_had_reached(
    database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = ["biomodels:BIOMD0000000001", "biomodels:BIOMD0000000002", "biomodels:BIOMD0000000003"]
    test_suite = Suite(name="resume-suite", description="three", sources=sources)
    monkeypatch.setattr(suites, "load_suites", lambda: {"resume-suite": test_suite})
    submitted: list[str] = []

    async def submit_source(suite: Suite, source: str, number: int, *_: object) -> str | None:
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

    async def submit_source(suite: Suite, source: str, number: int, *_: object) -> str | None:
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


@pytest.mark.asyncio
async def test_a_worker_shutting_down_gives_its_suite_run_back_at_once(
    database_service: DatabaseServiceSQL, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The next worker resumes the run straight away, without waiting out the lease (kill test, 2026-10-22)."""
    test_suite = Suite(name="handover-suite", description="two", sources=["biomodels:A1", "biomodels:B2"])
    monkeypatch.setattr(suites, "load_suites", lambda: {"handover-suite": test_suite})
    started = asyncio.Event()

    async def slow_source(suite: Suite, source: str, number: int, *_: object) -> str | None:
        started.set()
        await asyncio.sleep(3600)  # the pod goes away mid-source
        return None

    monkeypatch.setattr(suite_runs, "_submit_source", slow_source)
    number = await suite_runs.start(test_suite)
    first = SubmissionWorker(database_service, cast(Any, None), cast(Any, None), owner="first")
    await first.run_once()
    await asyncio.wait_for(started.wait(), timeout=10)
    await first.close()

    claimed = await database_service.get_comparisons_db().claim_suite_runs(owner="second", lease_seconds=60, limit=1)
    assert [(r.collection, r.number, r.next_source) for r in claimed] == [("handover-suite", number, 0)]
