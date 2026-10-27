"""Regression and reproducibility suites (docs/plan-sedml.md, phase 6): reviewed lists of SED-ML sources
(`examples/<name>/suite.yaml`) run on every solver, compared with each other, with references, and with the suite's
accepted baseline run."""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from compose_api.authentication import OptionalPrincipal, describe_caller, get_optional_principal
from compose_api.authorization import SuiteCurator
from compose_api.common.gateway.models import RouterConfig
from compose_api.dependencies import get_required_database_service
from compose_api.environments.versions import VersionUnavailableError, resolve_versions
from compose_api.sedml import service, suite_runs
from compose_api.sedml.models import (
    KnownProblem,
    KnownProblemClear,
    KnownProblemEdit,
    KnownProblemMark,
    SuiteVerifyResult,
)
from compose_api.sedml.suite_runs import SuiteRunInfo, SuiteRunView
from compose_api.sedml.suites import Suite, load_suites, suite

logger = logging.getLogger(__name__)

config = RouterConfig(router=APIRouter(), prefix="/suites", dependencies=[Depends(get_optional_principal)])


def _suite(name: str) -> Suite:
    found = suite(name)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No suite {name!r}.")
    return found


@config.router.get("", response_model=list[Suite], operation_id="list-suites", tags=["Suites"], summary="The suites")
async def list_suites(principal: OptionalPrincipal) -> list[Suite]:
    return list(load_suites().values())


@config.router.get(
    "/{name}/runs", response_model=list[SuiteRunInfo], operation_id="list-suite-runs", tags=["Suites"],
    summary="A suite's runs, newest first", responses={404: {"description": "No such suite"}},
)  # fmt: skip
async def list_suite_runs(name: str, principal: OptionalPrincipal) -> list[SuiteRunInfo]:
    return await suite_runs.runs(_suite(name))


@config.router.get(
    "/{name}/runs/{number}", response_model=SuiteRunView, operation_id="get-suite-run", tags=["Suites"],
    summary="One suite run: per source, agreement, references, and drift from the baseline run",
    responses={404: {"description": "No such suite or run"}},
)  # fmt: skip
async def get_suite_run(name: str, number: int, principal: OptionalPrincipal) -> SuiteRunView:
    found = await suite_runs.view(_suite(name), number)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Suite {name!r} has no run {number}.")
    return found


@config.router.post(
    "/{name}/run", response_model=SuiteRunInfo, operation_id="run-suite", tags=["Suites"],
    summary="Run every source of the suite on its solvers, in the environment versions named (in the background)",
    responses={
        400: {"description": "A version not named, malformed, or that runs cannot use"},
        404: {"description": "No such suite"},
        409: {"description": "A run of the suite is still submitting or running"},
    },
)  # fmt: skip
async def run_suite(
    name: str,
    principal: OptionalPrincipal,
    environment_version: Annotated[
        list[str],
        Query(
            min_length=1,
            description="The environment versions the suite runs in, required: environment@number (registry_env@2),"
            " environment@default, or default (every environment at its default). Stored with the run as numbers",
        ),
    ],
) -> SuiteRunInfo:
    """Every environment the suite's solvers use must be named (docs/plan-environment-versions.md, step 5): a suite
    run records exactly what it ran in, and is independent of the service release that started it."""
    s = _suite(name)
    try:
        versions = await resolve_versions(
            get_required_database_service(), environment_version, suite_runs.suite_environments(s), require_all=True
        )
    except (VersionUnavailableError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    running = await suite_runs.in_flight(s)
    if running is not None:  # one at a time (docs/plan-webapp-admin.md, A4)
        raise HTTPException(
            status_code=409,
            detail=f"Run {running} of {name!r} is still going (/suites/{name}/runs/{running}); start another once it"
            " has finished.",
        )
    number = await suite_runs.start(s, versions)
    logger.info(f"suite {name} run {number} started by {describe_caller(principal)} on {versions}")
    return SuiteRunInfo(number=number, created_at=None, status="submitting", environment_versions=versions)


@config.router.post(
    "/{name}/runs/{number}/verify", response_model=SuiteVerifyResult, operation_id="verify-suite-run",
    tags=["Suites"],
    summary="Queue a verification against biosim's /verify for a suite run's finished comparisons",
    responses={404: {"description": "No such suite or run"}},
)  # fmt: skip
async def verify_suite_run(
    name: str,
    number: int,
    principal: OptionalPrincipal,
    which: Annotated[
        Literal["failing", "all"],
        Query(
            description="failing: those that differ, are incomplete, or no agreeing reference settles; all: every one"
        ),
    ] = "failing",
) -> SuiteVerifyResult:
    found = await suite_runs.verify(_suite(name), number, which)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Suite {name!r} has no run {number}.")
    return found


# --- known problems (docs/plan-known-problems.md) ---------------------------------------------------------------------

_CURATOR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Anonymous"},
    403: {"description": "Not a suite curator, or suite curation is not configured"},
    404: {"description": "No such suite, problem or run"},
}


async def _run_numbers(name: str) -> set[int]:
    return {r.number for r in await get_required_database_service().get_comparisons_db().suite_runs(name)}


@config.router.get(
    "/{name}/problems", response_model=list[KnownProblem], operation_id="list-suite-problems", tags=["Suites"],
    summary="A suite's known problems: each solver's expected failures, open and cleared",
    responses={404: {"description": "No such suite"}},
)  # fmt: skip
async def list_suite_problems(
    name: str,
    principal: OptionalPrincipal,
    cleared: Annotated[bool | None, Query(description="only cleared (true) or only open (false) ones")] = None,
) -> list[KnownProblem]:
    _suite(name)
    found = await get_required_database_service().get_comparisons_db().known_problems(name)
    return [p for p in found if cleared is None or (p.cleared_run is not None) == cleared]


@config.router.post(
    "/{name}/problems", response_model=KnownProblem, status_code=201, operation_id="mark-suite-problem",
    tags=["Suites"], summary="Record a known problem of a solver on one of the suite's sources",
    responses={
        **_CURATOR_RESPONSES,
        400: {"description": "A source or solver the suite does not have"},
        409: {"description": "A problem is already open for that source and solver"},
    },
)  # fmt: skip
async def mark_suite_problem(name: str, mark: KnownProblemMark, curator: SuiteCurator) -> KnownProblem:
    s = _suite(name)
    if mark.source not in s.sources:
        raise HTTPException(status_code=400, detail=f"Suite {name!r} has no source {mark.source!r}.")
    solvers = [solver.id for solver in service.chosen_solvers(s.solvers)]
    if mark.solver is not None and mark.solver not in solvers:
        raise HTTPException(status_code=400, detail=f"Suite {name!r} runs {', '.join(solvers)}, not {mark.solver!r}.")
    if mark.seen_run is not None and mark.seen_run not in await _run_numbers(name):
        raise HTTPException(status_code=404, detail=f"Suite {name!r} has no run {mark.seen_run}.")
    added = await get_required_database_service().get_comparisons_db().add_known_problem(name, mark, curator.subject)
    if added is None:
        raise HTTPException(
            status_code=409, detail=f"A problem is already open for {mark.source} on {mark.solver or 'every solver'}."
        )
    logger.info(f"suite {name}: problem {added.problem_id} marked by {curator.subject}")
    return added


@config.router.patch(
    "/{name}/problems/{problem_id}", response_model=KnownProblem, operation_id="edit-suite-problem",
    tags=["Suites"], summary="Change a known problem's category or reason", responses=_CURATOR_RESPONSES,
)  # fmt: skip
async def edit_suite_problem(name: str, problem_id: int, edit: KnownProblemEdit, curator: SuiteCurator) -> KnownProblem:
    _suite(name)
    edited = (
        await get_required_database_service()
        .get_comparisons_db()
        .edit_known_problem(name, problem_id, edit.category, edit.reason)
    )
    if edited is None:
        raise HTTPException(status_code=404, detail=f"Suite {name!r} has no problem {problem_id}.")
    return edited


@config.router.post(
    "/{name}/problems/{problem_id}/clear", response_model=KnownProblem, operation_id="clear-suite-problem",
    tags=["Suites"],
    summary="Clear a known problem at the suite run that shows it fixed; earlier runs still excuse it",
    responses={**_CURATOR_RESPONSES, 409: {"description": "Already cleared"}},
)  # fmt: skip
async def clear_suite_problem(
    name: str, problem_id: int, clear: KnownProblemClear, curator: SuiteCurator
) -> KnownProblem:
    _suite(name)
    if clear.run not in await _run_numbers(name):
        raise HTTPException(status_code=404, detail=f"Suite {name!r} has no run {clear.run}.")
    db = get_required_database_service().get_comparisons_db()
    found = next((p for p in await db.known_problems(name) if p.problem_id == problem_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Suite {name!r} has no problem {problem_id}.")
    cleared = await db.clear_known_problem(name, problem_id, clear.run, curator.subject)
    if cleared is None:
        raise HTTPException(status_code=409, detail=f"Problem {problem_id} was cleared at run {found.cleared_run}.")
    logger.info(f"suite {name}: problem {problem_id} cleared at run {clear.run} by {curator.subject}")
    return cleared
