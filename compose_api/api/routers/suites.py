"""Regression and reproducibility suites (docs/plan-sedml.md, phase 6): reviewed lists of SED-ML sources
(`examples/<name>/suite.yaml`) run on every solver, compared with each other, with references, and with the suite's
accepted baseline run."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from compose_api.authentication import OptionalPrincipal, describe_caller, get_optional_principal
from compose_api.common.gateway.models import RouterConfig
from compose_api.dependencies import get_required_database_service
from compose_api.environments.versions import VersionUnavailableError, resolve_versions
from compose_api.sedml import suite_runs
from compose_api.sedml.models import SuiteVerifyResult
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
