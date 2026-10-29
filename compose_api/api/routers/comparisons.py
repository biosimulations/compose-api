"""Comparisons: one SED-ML task run on several solvers, scored once every run has finished (docs/plan-sedml.md, D4)."""

import math
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status

from compose_api.api.errors import error
from compose_api.api.routers.favorites import starred_refs
from compose_api.authentication import get_optional_principal
from compose_api.authorization import OptionalCaller, readable_clause, readable_comparison
from compose_api.common.gateway.models import RouterConfig
from compose_api.dependencies import get_required_database_service
from compose_api.favorites import FavoriteKind
from compose_api.sedml import service, verifications
from compose_api.sedml.models import Comparison, ComparisonPage, ComparisonSeries, Verification, VerifyRequest

config = RouterConfig(router=APIRouter(), prefix="/comparisons", dependencies=[Depends(get_optional_principal)])


def _flagged(view: Comparison, starred: set[str]) -> Comparison:
    """The comparison, saying whether the caller starred it."""
    return view.model_copy(update={"favorite": str(view.comparison_id) in starred})


@config.router.get(
    path="",
    response_model=ComparisonPage,
    operation_id="list-comparisons",
    responses={401: error("`favorite` without a signed-in caller")},
    tags=["SED-ML"],
    summary="List comparisons, newest first",
)
async def list_comparisons(
    caller: OptionalCaller,
    source: Annotated[str | None, Query(description="Only this source, e.g. upload:x.omex or biomodels:BIOMD…")] = None,
    favorite: Annotated[
        bool,
        Query(description="Only those the caller starred (`PUT /favorites/comparison/{id}`); needs a signed-in caller"),
    ] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ComparisonPage:
    if favorite and caller is None:
        raise HTTPException(
            status_code=401,
            detail="Listing your favorite comparisons needs a signed-in caller",
            headers={"WWW-Authenticate": "Bearer"},
        )
    rows, total = (
        await get_required_database_service()
        .get_comparisons_db()
        .page(
            limit,
            offset,
            source,
            readable=readable_clause(caller),
            favorite_of=caller.subject if favorite and caller is not None else None,
        )
    )
    following = offset + len(rows)
    statuses = await service.member_statuses(rows)
    starred = await starred_refs(caller, FavoriteKind.COMPARISON)
    return ComparisonPage(
        comparisons=[_flagged(await service.comparison_view(r, statuses), starred) for r in rows],
        total=total,
        next_offset=following if following < total else None,
    )


@config.router.get(
    path="/{comparison_id}",
    response_model=Comparison,
    operation_id="get-comparison",
    tags=["SED-ML"],
    summary="One comparison: its runs, and per report and data set each solver pair's score",
    responses={404: error("No such comparison")},
)
async def get_comparison(comparison_id: int, caller: OptionalCaller) -> Comparison:
    row = await readable_comparison(caller, comparison_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Comparison {comparison_id} not found.")
    return _flagged(await service.comparison_view(row), await starred_refs(caller, FavoriteKind.COMPARISON))


@config.router.get(
    path="/{comparison_id}/series",
    response_model=ComparisonSeries,
    operation_id="get-comparison-series",
    tags=["SED-ML"],
    summary="One report's columns from each run and each reference, for overlays",
    responses={404: error("No such comparison or report")},
)
async def get_comparison_series(comparison_id: int, report: str, caller: OptionalCaller) -> ComparisonSeries:
    row = await readable_comparison(caller, comparison_id)
    reports_info = (row.comparison.settings.get("reports") or {}) if row is not None else {}
    if row is None or report not in reports_info:
        raise HTTPException(status_code=404, detail=f"Comparison {comparison_id} has no report {report!r}.")
    found, _missing = await service.member_reports(row.comparison.settings, row)

    def finite(columns: dict[str, list[float]]) -> dict[str, list[float | None]]:
        # JSON has no NaN: a missing value is null (a gap in a plot), never shifted or zeroed
        return {k: [v if math.isfinite(v) else None for v in col] for k, col in columns.items()}

    return ComparisonSeries(
        report=report,
        labels=list(reports_info[report].get("labels", [])),
        solvers={solver: finite(r.get(report, {})) for solver, r in found.items()},
        references={ref.origin: finite(ref.reports.get(report, {})) for ref in row.references},
    )


@config.router.post(
    path="/{comparison_id}/verify",
    response_model=Verification,
    operation_id="verify-comparison",
    tags=["SED-ML"],
    summary="Check a comparison against BioSimulators' simulators through biosim's /verify (queued; 201 when new)",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {
            "model": Verification,
            "description": "A verification for the same simulators is already queued or running, or failed while "
            "biosim was still working on it and is now polled again; it is returned",
        },
        201: {"description": "Queued"},
        404: error("No such comparison"),
    },
)
async def verify_comparison(
    comparison_id: int,
    caller: OptionalCaller,
    response: Response,
    request: Annotated[VerifyRequest | None, Body()] = None,
) -> Verification:
    row = await readable_comparison(caller, comparison_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Comparison {comparison_id} not found.")
    verification, created = await verifications.queue(row, request.simulators if request else None)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return verifications.view(verification)


@config.router.get(
    path="/{comparison_id}/verifications",
    response_model=list[Verification],
    operation_id="list-comparison-verifications",
    tags=["SED-ML"],
    summary="A comparison's verifications against biosim's /verify, oldest first",
    responses={404: error("No such comparison")},
)
async def list_comparison_verifications(comparison_id: int, caller: OptionalCaller) -> list[Verification]:
    row = await readable_comparison(caller, comparison_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Comparison {comparison_id} not found.")
    found = await get_required_database_service().get_comparisons_db().verifications(comparison_id)
    result = (await service.comparison_view(row)).result if found else None
    return [verifications.view(v, result) for v in found]
