"""Comparisons: one SED-ML task run on several solvers, scored once every run has finished (docs/plan-sedml.md, D4)."""

import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from compose_api.authentication import OptionalPrincipal, get_optional_principal
from compose_api.common.gateway.models import RouterConfig
from compose_api.dependencies import get_required_database_service
from compose_api.sedml import service
from compose_api.sedml.models import Comparison, ComparisonPage, ComparisonSeries

config = RouterConfig(router=APIRouter(), prefix="/comparisons", dependencies=[Depends(get_optional_principal)])


@config.router.get(
    path="",
    response_model=ComparisonPage,
    operation_id="list-comparisons",
    tags=["SED-ML"],
    summary="List comparisons, newest first",
)
async def list_comparisons(
    principal: OptionalPrincipal,
    source: Annotated[str | None, Query(description="Only this source, e.g. upload:x.omex or biomodels:BIOMD…")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ComparisonPage:
    # public: runs are anonymous and public (docs/plan-sedml.md, D9)
    rows, total = await get_required_database_service().get_comparisons_db().page(limit, offset, source)
    following = offset + len(rows)
    return ComparisonPage(
        comparisons=[await service.comparison_view(r) for r in rows],
        total=total,
        next_offset=following if following < total else None,
    )


@config.router.get(
    path="/{comparison_id}",
    response_model=Comparison,
    operation_id="get-comparison",
    tags=["SED-ML"],
    summary="One comparison: its runs, and per report and data set each solver pair's score",
    responses={404: {"description": "No such comparison"}},
)
async def get_comparison(comparison_id: int, principal: OptionalPrincipal) -> Comparison:
    row = await get_required_database_service().get_comparisons_db().get(comparison_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Comparison {comparison_id} not found.")
    return await service.comparison_view(row)


@config.router.get(
    path="/{comparison_id}/series",
    response_model=ComparisonSeries,
    operation_id="get-comparison-series",
    tags=["SED-ML"],
    summary="One report's columns from each run and each reference, for overlays",
    responses={404: {"description": "No such comparison or report"}},
)
async def get_comparison_series(comparison_id: int, report: str, principal: OptionalPrincipal) -> ComparisonSeries:
    row = await get_required_database_service().get_comparisons_db().get(comparison_id)
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
