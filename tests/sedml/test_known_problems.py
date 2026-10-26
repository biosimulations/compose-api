"""Known problems (docs/plan-known-problems.md): who may mark and clear them, which runs they apply to, and how a
suite run's row is judged against them: excused only through its own solvers, resolved when the solver now agrees."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from compose_api.api.routers import suites as suites_router
from compose_api.authorization import get_caller
from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.sedml import service, suite_runs, suites
from compose_api.sedml.models import Comparison, ComparisonMember, KnownProblem
from compose_api.sedml.suite_runs import judge
from compose_api.sedml.suites import ExpectedFailure, Suite

ROLE = "curator"
SUITE = Suite(
    name="kp-suite",
    description="known problems",
    sources=["biomodels:A1", "biomodels:B2", "biomodels:C3", "biomodels:D4"],
    solvers=["copasi", "tellurium", "vcell"],
)

VIEWED = SUITE.model_copy(update={"name": "kp-viewed"})  # its own problems: the database is shared by these tests


@dataclass(frozen=True)
class FakeCaller:
    subject: str
    roles: frozenset[str] = field(default_factory=lambda: frozenset({"user"}))


CURATOR = FakeCaller("auth0|curator", frozenset({"user", ROLE}))
USER = FakeCaller("auth0|alice")


@pytest_asyncio.fixture
async def app(database_service: DatabaseServiceSQL, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[FastAPI]:
    monkeypatch.setattr(suites, "load_suites", lambda: {SUITE.name: SUITE, VIEWED.name: VIEWED})
    app = FastAPI()
    app.include_router(suites_router.config.router, prefix=suites_router.config.prefix)
    yield app


def _as(app: FastAPI, caller: FakeCaller | None) -> httpx.AsyncClient:
    async def override() -> FakeCaller | None:
        return caller

    app.dependency_overrides[get_caller] = override
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


def _result(pairs: dict[str, bool | None]) -> dict[str, Any]:
    """A comparison result with one report and one label, each solver pair's verdict as given."""
    return {"reports": {"r": {"labels": {"x": {p: {"close": c} for p, c in pairs.items()}}}}}


def test_a_known_problem_excuses_only_its_solver() -> None:
    done = {"copasi": "completed", "tellurium": "completed", "vcell": "failed"}
    vcell_failed = _result({"copasi|tellurium": True, "copasi|vcell": None, "tellurium|vcell": None})
    assert judge(False, done, vcell_failed, {"vcell"}) == (True, [])
    # the solvers without a problem disagree with each other: not excused (BIOMD 206 and 248)
    others_differ = _result({"copasi|tellurium": False, "copasi|vcell": None, "tellurium|vcell": None})
    assert judge(False, done, others_differ, {"vcell"}) == (False, [])
    # a solver without a problem failed: not excused
    assert judge(False, {**done, "tellurium": "failed"}, vcell_failed, {"vcell"}) == (False, [])
    # only one solver left without a problem: nothing to compare, excused
    assert judge(False, {**done, "tellurium": "failed"}, vcell_failed, {"vcell", "tellurium"}) == (True, [])


def test_a_known_problem_that_no_longer_occurs_is_resolved() -> None:
    done = {"copasi": "completed", "tellurium": "completed", "vcell": "completed"}
    agree = _result({"copasi|tellurium": True, "copasi|vcell": True, "tellurium|vcell": True})
    assert judge(True, done, agree, {"vcell"}) == (False, ["vcell"])
    # vcell runs now but differs: still a problem, still excused (BIOMD 56 and 168)
    differs = _result({"copasi|tellurium": True, "copasi|vcell": False, "tellurium|vcell": False})
    assert judge(False, done, differs, {"vcell"}) == (True, [])
    # a reference's verdict is not a solver pair
    with_reference = _result({"copasi|tellurium": True, "copasi|vcell": True, "tellurium|vcell": True})
    with_reference["reports"]["r"]["labels"]["x"]["vcell|archive"] = {"close": False, "reference": True}
    assert judge(True, done, with_reference, {"vcell"}) == (False, ["vcell"])


def _problem(problem_id: int, solver: str | None, cleared_run: int | None = None) -> KnownProblem:
    return KnownProblem(
        problem_id=problem_id, suite=SUITE.name, source="biomodels:A1", solver=solver, category="C",
        reason=f"reason {problem_id}", marked_by="x", cleared_run=cleared_run,
    )  # fmt: skip


def test_a_problem_applies_to_the_runs_before_the_one_that_cleared_it() -> None:
    known = [_problem(1, "vcell", cleared_run=4), _problem(2, None)]
    assert suite_runs._problems_for(SUITE, known, 3) == {
        ("biomodels:A1", "vcell"): "reason 1",
        ("biomodels:A1", None): "reason 2",
    }
    assert suite_runs._problems_for(SUITE, known, 4) == {("biomodels:A1", None): "reason 2"}
    # the suite file's entries count as open problems until they are moved
    legacy = SUITE.model_copy(
        update={"expected": [ExpectedFailure(source="biomodels:B2", solver="tellurium", reason="delay")]}
    )
    assert suite_runs._problems_for(legacy, [], 9) == {("biomodels:B2", "tellurium"): "delay"}


@pytest.mark.asyncio
async def test_reading_is_public_and_curating_needs_the_role(
    app: FastAPI, database_service: DatabaseServiceSQL
) -> None:
    mark = {"source": "biomodels:A1", "solver": "vcell", "category": "DELAY", "reason": "delay equations"}
    async with _as(app, None) as anonymous:
        assert (await anonymous.get("/suites/kp-suite/problems")).json() == []
        assert (await anonymous.post("/suites/kp-suite/problems", json=mark)).status_code == 401
    async with _as(app, CURATOR) as curator:
        refused = await curator.post("/suites/kp-suite/problems", json=mark)
        assert refused.status_code == 403 and "not configured" in refused.json()["detail"]
    with override_settings(suite_curator_role=ROLE):
        async with _as(app, USER) as user:
            assert (await user.post("/suites/kp-suite/problems", json=mark)).status_code == 403
            assert (await user.patch("/suites/kp-suite/problems/1", json={"reason": "x"})).status_code == 403
            assert (await user.post("/suites/kp-suite/problems/1/clear", json={"run": 1})).status_code == 403


@pytest.mark.asyncio
async def test_mark_edit_and_clear(app: FastAPI, database_service: DatabaseServiceSQL) -> None:
    db = database_service.get_comparisons_db()
    for _ in range(2):
        await db.new_suite_run(SUITE.name, SUITE.sources, None)
    mark = {
        "source": "biomodels:A1",
        "solver": "vcell",
        "category": "DELAY",
        "reason": "delay equations",
        "seen_run": 1,
    }
    with override_settings(suite_curator_role=ROLE):
        async with _as(app, CURATOR) as curator:
            for bad, code in (
                ({**mark, "source": "biomodels:Z9"}, 400),
                ({**mark, "solver": "amici"}, 400),
                ({**mark, "seen_run": 7}, 404),
                ({**mark, "category": " "}, 422),
            ):
                assert (await curator.post("/suites/kp-suite/problems", json=bad)).status_code == code, bad
            added = await curator.post("/suites/kp-suite/problems", json=mark)
            assert added.status_code == 201
            problem = added.json()
            assert problem["marked_by"] == "auth0|curator" and problem["cleared_run"] is None
            assert (await curator.post("/suites/kp-suite/problems", json=mark)).status_code == 409  # one open at a time
            whole = await curator.post("/suites/kp-suite/problems", json={**mark, "solver": None, "reason": "bad SBML"})
            assert whole.status_code == 201  # the whole source is a different problem

            pid = problem["problem_id"]
            edited = await curator.patch(f"/suites/kp-suite/problems/{pid}", json={"category": "MATHML_PARSING"})
            assert edited.json()["category"] == "MATHML_PARSING" and edited.json()["reason"] == "delay equations"
            assert (await curator.patch("/suites/kp-suite/problems/999", json={"reason": "x"})).status_code == 404

            assert (await curator.post(f"/suites/kp-suite/problems/{pid}/clear", json={"run": 9})).status_code == 404
            cleared = await curator.post(f"/suites/kp-suite/problems/{pid}/clear", json={"run": 2})
            assert cleared.json()["cleared_run"] == 2 and cleared.json()["cleared_by"] == "auth0|curator"
            assert (await curator.post(f"/suites/kp-suite/problems/{pid}/clear", json={"run": 2})).status_code == 409
            # cleared, so a new problem may be opened for the same solver
            assert (await curator.post("/suites/kp-suite/problems", json=mark)).status_code == 201

            listed = (await curator.get("/suites/kp-suite/problems")).json()
            assert [p["problem_id"] for p in listed] == [pid, whole.json()["problem_id"], pid + 2]
            open_ = (await curator.get("/suites/kp-suite/problems", params={"cleared": False})).json()
            assert pid not in [p["problem_id"] for p in open_] and len(open_) == 2


@pytest.mark.asyncio
async def test_a_suite_run_is_judged_against_its_known_problems(
    app: FastAPI, database_service: DatabaseServiceSQL, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each row as run 4 of biomodels-curated-300 showed them: VCell's import failed (A1), failed while COPASI and
    Tellurium also differ (B2), runs now and agrees (C3); D4 has no problem and differs."""
    db = database_service.get_comparisons_db()
    _, number = await db.new_suite_run(VIEWED.name, VIEWED.sources, None)
    vcell_failed = {"copasi": "completed", "tellurium": "completed", "vcell": "failed"}
    every = {"copasi": "completed", "tellurium": "completed", "vcell": "completed"}
    rows: dict[str, tuple[str, dict[str, str], dict[str, bool | None]]] = {
        "biomodels:A1": ("incomplete", vcell_failed, {"copasi|tellurium": True, "copasi|vcell": None}),
        "biomodels:B2": ("incomplete", vcell_failed, {"copasi|tellurium": False, "copasi|vcell": None}),
        "biomodels:C3": ("complete", every, {"copasi|tellurium": True, "copasi|vcell": True, "tellurium|vcell": True}),
        "biomodels:D4": (
            "complete",
            every,
            {"copasi|tellurium": True, "copasi|vcell": False, "tellurium|vcell": False},
        ),
    }
    ids = {}
    for source in rows:
        ids[await db.insert("n", source, "s.sedml", "t", {}, collection=VIEWED.name, suite_run=number)] = source

    async def view(row: Any, statuses: Any = None) -> Comparison:
        source = ids[row.comparison.id]
        status, members, pairs = rows[source]
        result = _result(pairs)
        return Comparison(
            comparison_id=row.comparison.id, name="n", source=source, sedml="s.sedml", task="t", status=status,  # type: ignore[arg-type]
            settings={}, members=[ComparisonMember(solver=s, simulation_id=0, status=m) for s, m in members.items()],
            result=result, close=status == "complete" and all(pairs.values()),
        )  # fmt: skip

    monkeypatch.setattr(service, "comparison_view", view)
    from compose_api.sedml.models import KnownProblemMark

    for source in ("biomodels:A1", "biomodels:B2", "biomodels:C3"):
        mark = KnownProblemMark(source=source, solver="vcell", category="NONINTEGER_STOICH", reason="0.5")
        await db.add_known_problem(VIEWED.name, mark, "auth0|curator")

    async with _as(app, None) as anonymous:
        found = (await anonymous.get(f"/suites/kp-viewed/runs/{number}")).json()
    by_source = {r["source"]: r for r in found["rows"]}
    assert by_source["biomodels:A1"]["excused"] is True and by_source["biomodels:A1"]["known_problems"] == {
        "vcell": "0.5"
    }
    assert by_source["biomodels:B2"]["excused"] is False
    assert by_source["biomodels:C3"]["resolved"] == ["vcell"] and by_source["biomodels:C3"]["close"] is True
    assert by_source["biomodels:D4"]["known_problems"] == {} and by_source["biomodels:D4"]["excused"] is False
    summary = found["summary"]
    assert (summary["agree"], summary["differ"], summary["excused"], summary["resolved"]) == (1, 2, 1, 1)
