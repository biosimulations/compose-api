"""Running a suite and reading a suite run (compose_api/sedml/suites.py; docs/plan-sedml.md, phase 6)."""

import asyncio
import logging
from typing import Any

from fastapi import BackgroundTasks
from pydantic import BaseModel

from compose_api.dependencies import get_required_database_service
from compose_api.sedml import service, sources
from compose_api.sedml.compare import compare
from compose_api.sedml.suites import Suite
from compose_api.sedml.translator import TranslatorUnavailableError

logger = logging.getLogger(__name__)
_running: set[asyncio.Task[None]] = set()


class Drift(BaseModel):
    """One solver's result against its own result in the suite's baseline run."""

    close: bool | None
    worst_label: str | None = None
    worst_score: float | str | None = None


class SuiteRunRow(BaseModel):
    source: str
    task: str | None = None
    comparison_id: int | None = None
    status: str
    close: bool | None = None
    close_to_references: bool | None = None
    worst_label: str | None = None
    worst_score: float | str | None = None
    drift: dict[str, Drift] | None = None
    expected: str | None = None
    failure: str | None = None


class SuiteRunView(BaseModel):
    suite: str
    number: int
    created_at: str | None
    status: str
    baseline: int | None
    rows: list[SuiteRunRow]
    summary: dict[str, int]


class SuiteRunInfo(BaseModel):
    number: int
    created_at: str | None
    status: str


async def start(suite: Suite) -> int:
    """A new run of the suite, its sources fetched, translated and submitted in the background; its number."""
    run_id, number = await get_required_database_service().get_comparisons_db().new_suite_run(suite.name)
    task = asyncio.create_task(_submit_all(suite, run_id, number))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return number


async def _submit_all(suite: Suite, run_id: int, number: int) -> None:
    failures: dict[str, Any] = {}
    jobs = BackgroundTasks()
    solvers = service.chosen_solvers(suite.solvers)
    for source in suite.sources:
        kind, _, ident = source.partition(":")
        try:
            references = None
            if kind == "biomodels":
                path = await sources.biomodel_archive(ident)
            else:
                path = await sources.project_archive(ident)
                info = await sources.project(ident)
                reference = await sources.project_reference(ident)
                references = {f"biosimulations:{info.simulator or info.run}": reference} if reference else None
            translation = await service.translate_upload(path, solvers)
            ids = await service.submit(
                translation, path, source, solvers, None, [suite.name], None, suite.tolerances, jobs,
                references=references, collection=suite.name, suite_run=number,
            )  # fmt: skip
            if not ids:
                failures[source] = (
                    "no task was accepted by any solver: "
                    + "; ".join(f"{f.code} {f.message}" for f in translation.findings if f.severity == "error")[:2000]
                )
        except (
            sources.SourceNotFoundError,
            sources.SourceUnavailableError,
            TranslatorUnavailableError,
            ValueError,
        ) as e:
            failures[source] = str(e)[:2000]
        except Exception as e:  # one source must not stop the rest
            logger.exception("suite %s run %d: %s failed", suite.name, number, source)
            failures[source] = f"{type(e).__name__}: {e}"[:2000]
    await get_required_database_service().get_comparisons_db().finish_suite_run(run_id, failures)
    await jobs()  # the runs' submissions (run_simulation's background work)


async def runs(suite: Suite) -> list[SuiteRunInfo]:
    found = await get_required_database_service().get_comparisons_db().suite_runs(suite.name)
    return [SuiteRunInfo(number=r.number, created_at=service._iso(r.created_at), status=r.status) for r in found]


async def view(suite: Suite, number: int) -> SuiteRunView | None:
    db = get_required_database_service().get_comparisons_db()
    run = next((r for r in await db.suite_runs(suite.name) if r.number == number), None)
    if run is None:
        return None
    rows: list[SuiteRunRow] = []
    baseline = {}
    if suite.baseline is not None and suite.baseline != number:
        baseline = {
            (r.comparison.source, r.comparison.task): r for r in await db.suite_comparisons(suite.name, suite.baseline)
        }
    for row in await db.suite_comparisons(suite.name, number):
        c = await service.comparison_view(row)
        result = c.result or {}
        worst = _worst(result)
        entry = SuiteRunRow(
            source=c.source, task=c.task, comparison_id=c.comparison_id, status=c.status, close=c.close,
            close_to_references=result.get("close_to_references"), worst_label=worst[0], worst_score=worst[1],
        )  # fmt: skip
        expected = suite.expected_for(c.source)
        entry.expected = expected.reason if expected else None
        before = baseline.get((c.source, c.task))
        if before is not None and c.status != "running":
            entry.drift = await _drift(row, before)
        rows.append(entry)
    for source, why in (run.failures or {}).items():
        expected = suite.expected_for(source)
        rows.append(
            SuiteRunRow(
                source=source, status="failed", failure=str(why), expected=expected.reason if expected else None
            )
        )
    summary = {
        "comparisons": sum(1 for r in rows if r.comparison_id is not None),
        "agree": sum(1 for r in rows if r.close is True),
        "differ": sum(1 for r in rows if r.close is False and not r.expected),
        "expected": sum(1 for r in rows if r.expected),
        "running": sum(1 for r in rows if r.status == "running"),
        "failed": sum(1 for r in rows if r.failure and not r.expected),
        "drifted": sum(1 for r in rows if r.drift and any(d.close is False for d in r.drift.values())),
    }
    return SuiteRunView(
        suite=suite.name, number=number, created_at=service._iso(run.created_at), status=run.status,
        baseline=suite.baseline, rows=rows, summary=summary,
    )  # fmt: skip


def _worst(result: dict[str, Any]) -> tuple[str | None, float | str | None]:
    worst: tuple[str | None, float | str | None] = (None, None)
    for report in (result.get("reports") or {}).values():
        w = report.get("worst") or {}
        score = w.get("score")
        if score is not None and (worst[1] is None or _num(score) > _num(worst[1])):
            worst = (w.get("label"), score)
    return worst


def _num(value: float | str | None) -> float:
    return float("inf") if value == "inf" else float(value or 0.0)


async def _drift(current: Any, before: Any) -> dict[str, Drift]:
    """Each solver against its own baseline result, by the comparison's tolerances."""
    from compose_api.sedml.models import Tolerances

    now, _ = await service.member_reports(current.comparison.settings, current)
    then, _ = await service.member_reports(before.comparison.settings, before)
    labels = {r: list(info.get("labels", [])) for r, info in (current.comparison.settings.get("reports") or {}).items()}
    tolerances = Tolerances.model_validate(current.comparison.settings.get("tolerances", {}))
    drift: dict[str, Drift] = {}
    for solver in now:
        if solver not in then:
            drift[solver] = Drift(close=None)
            continue
        result = compare({"now": now[solver], "baseline": then[solver]}, labels, tolerances)
        worst = _worst(result)
        drift[solver] = Drift(close=bool(result["close"]), worst_label=worst[0], worst_score=worst[1])
    return drift
