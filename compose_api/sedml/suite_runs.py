"""Running a suite and reading a suite run (compose_api/sedml/suites.py; docs/plan-sedml.md, phase 6)."""

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import BackgroundTasks
from pydantic import BaseModel, Field

from compose_api.db.services.comparisons_db import ClaimedSuiteRun
from compose_api.dependencies import get_required_database_service
from compose_api.sedml import service, sources, suites
from compose_api.sedml.compare import compare
from compose_api.sedml.models import KnownProblem, SuiteVerifyResult
from compose_api.sedml.suites import Suite
from compose_api.sedml.translator import TranslatorUnavailableError

logger = logging.getLogger(__name__)


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
    expected: str | None = Field(default=None, description="why the whole source is excused, if it is")
    known_problems: dict[str, str] = Field(
        default_factory=dict, description="each solver's known problem here, by solver: its reason"
    )
    excused: bool = Field(
        default=False,
        description="the row fails or differs only through solvers with a known problem; the others agree",
    )
    resolved: list[str] = Field(
        default_factory=list, description="solvers with a known problem here that completed and agree: clear it"
    )
    failure: str | None = None
    verification: str | None = None  # the newest verification's state (docs/plan-verify-oracle.md)
    verify_close: bool | None = None


class SuiteRunView(BaseModel):
    suite: str
    number: int
    created_at: str | None
    status: str
    baseline: int | None
    rows: list[SuiteRunRow]
    summary: dict[str, int]
    environment_versions: dict[str, int] = Field(
        default_factory=dict, description="The environment versions its runs use, {environment: number}"
    )


class SuiteRunInfo(BaseModel):
    number: int
    created_at: str | None
    status: str
    environment_versions: dict[str, int] = Field(
        default_factory=dict,
        description="The environment versions its runs use, {environment: number}; empty for runs started before"
        " suites named them (theirs got the default)",
    )


#: Where a suite's runs wait, and how far behind interactive ones (docs/plan-durable-submission.md, Q3).
SUITE_PRIORITY = -10


def suite_queue(name: str) -> str:
    return f"suite:{name}"


def suite_environments(suite: Suite) -> set[str]:
    """The environments a suite's solvers run in (registry/solvers.yaml)."""
    return {s.environment for s in service.chosen_solvers(suite.solvers)}


async def start(suite: Suite, environment_versions: dict[str, int] | None = None) -> int:
    """A new run of the suite, recorded with its sources and the environment versions its runs use (resolved by the
    caller with `environments.versions.resolve_versions`, which the route requires; none: the defaults). The
    submission worker fetches, translates and submits them, resuming after a restart from the source it had reached.
    Its number."""
    from compose_api.dependencies import get_submission_worker  # late: dependencies imports the simulation modules

    _, number = (
        await get_required_database_service()
        .get_comparisons_db()
        .new_suite_run(suite.name, suite.sources, environment_versions)
    )
    worker = get_submission_worker()
    if worker is not None:
        worker.kick()
    return number


async def submit_run(run: ClaimedSuiteRun, owner: str) -> None:
    """Submit a claimed suite run's sources from where it got to: skip one already submitted (by an earlier worker),
    record each one's progress (and its failure) before the next, and finish the run after the last. Stops quietly if
    the run was taken over (its lease lost)."""
    db = get_required_database_service().get_comparisons_db()
    found = suites.suite(run.collection)
    sources_ = list(run.sources or [])
    for index in range(run.next_source, len(sources_)):
        source = sources_[index]
        failure = None
        if found is None:
            failure = (source, f"the suite {run.collection!r} is no longer defined")
        elif not await db.suite_source_submitted(run.collection, run.number, source):
            why = await _submit_source(found, source, run.number, run.environment_versions)
            failure = (source, why) if why is not None else None
        if not await db.advance_suite_run(run.id, owner, index + 1, failure):
            logger.warning(f"suite {run.collection} run {run.number}: taken over at source {index}; stopping")
            return
    await db.finish_suite_run(run.id, owner)


async def _submit_source(
    suite: Suite, source: str, number: int, environment_versions: dict[str, int] | None = None
) -> str | None:
    """Fetch, translate and queue one source's runs; why not, if it could not be."""
    jobs = BackgroundTasks()
    solvers = service.chosen_solvers(suite.solvers)
    kind, _, ident = source.partition(":")
    try:
        references = None
        if kind == "biomodels":
            path = await sources.biomodel_archive(ident)
            # its original BioSimulators runs on biosimulations.org (docs/plan-verify-oracle.md, V1)
            references = await sources.biomodel_references(ident) or None
        else:
            path = await sources.project_archive(ident)
            info = await sources.project(ident)
            reference = await sources.project_reference(ident)
            references = {f"biosimulations:{info.simulator or info.run}": reference} if reference else None
        translation = await service.translate_upload(path, solvers)
        ids = await service.submit(
            translation, path, source, solvers, None, [suite.name], None, suite.tolerances, jobs,
            references=references, collection=suite.name, suite_run=number,
            queue=suite_queue(suite.name), priority=SUITE_PRIORITY, batch=True,
            environment_versions=environment_versions or None,
        )  # fmt: skip
        if not ids:
            return (
                "no task was accepted by any solver: "
                + "; ".join(f"{f.code} {f.message}" for f in translation.findings if f.severity == "error")[:2000]
            )
    except (
        sources.SourceNotFoundError,
        sources.SourceUnavailableError,
        TranslatorUnavailableError,
        ValueError,
    ) as e:
        return str(e)[:2000]
    except Exception as e:  # one source must not stop the rest
        logger.exception("suite %s run %d: %s failed", suite.name, number, source)
        return f"{type(e).__name__}: {e}"[:2000]
    finally:
        await jobs()  # cleanup only: the runs themselves are queued for the submission worker
    return None


async def runs(suite: Suite) -> list[SuiteRunInfo]:
    db = get_required_database_service().get_comparisons_db()
    found = await db.suite_runs(suite.name)
    versions = await db.environment_versions_of(found)
    return [
        SuiteRunInfo(
            number=r.number,
            created_at=service._iso(r.created_at),
            status=r.status,
            environment_versions=versions.get(r.id, {}),
        )
        for r in found
    ]


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
    problems = _problems_for(suite, await db.known_problems(suite.name), number)
    found = await db.suite_comparisons(suite.name, number)
    statuses = await service.member_statuses(found)
    for row in found:
        c = await service.comparison_view(row, statuses)
        result = c.result or {}
        worst = _worst(result)
        entry = SuiteRunRow(
            source=c.source, task=c.task, comparison_id=c.comparison_id, status=c.status, close=c.close,
            close_to_references=result.get("close_to_references"), worst_label=worst[0], worst_score=worst[1],
        )  # fmt: skip
        whole = problems.get((c.source, None))
        entry.expected = whole
        entry.known_problems = {
            solver: reason for (source, solver), reason in problems.items() if source == c.source and solver
        }
        if entry.known_problems and c.status != "running":
            members = {m.solver: m.status for m in c.members}
            entry.excused, entry.resolved = judge(c.close, members, c.result, set(entry.known_problems))
        before = baseline.get((c.source, c.task))
        if before is not None and c.status != "running":
            entry.drift = await _drift(row, before)
        rows.append(entry)
    latest = await db.latest_verifications([r.comparison_id for r in rows if r.comparison_id is not None])
    for entry in rows:
        v = latest.get(entry.comparison_id or -1)
        if v is not None:
            entry.verification, entry.verify_close = v.state, v.verify_close
    for source, why in (run.failures or {}).items():
        rows.append(
            SuiteRunRow(source=source, status="failed", failure=str(why), expected=problems.get((source, None)))
        )
    summary = {
        "comparisons": sum(1 for r in rows if r.comparison_id is not None),
        "agree": sum(1 for r in rows if r.close is True),
        "differ": sum(1 for r in rows if r.close is False and not r.expected and not r.excused),
        "expected": sum(1 for r in rows if r.expected),
        "excused": sum(1 for r in rows if r.excused and not r.expected),
        "resolved": sum(1 for r in rows if r.resolved),
        "running": sum(1 for r in rows if r.status == "running"),
        "failed": sum(1 for r in rows if r.failure and not r.expected),
        "drifted": sum(1 for r in rows if r.drift and any(d.close is False for d in r.drift.values())),
        "verifying": sum(1 for r in rows if r.verification in ("requested", "submitted")),
        "verified": sum(1 for r in rows if r.verification == "completed"),
        "oracle_agrees": sum(1 for r in rows if r.verify_close is True),
    }
    return SuiteRunView(
        suite=suite.name, number=number, created_at=service._iso(run.created_at), status=run.status,
        baseline=suite.baseline, rows=rows, summary=summary,
        environment_versions=(await db.environment_versions_of([run])).get(run.id, {}),
    )  # fmt: skip


async def verify(suite: Suite, number: int, which: str) -> SuiteVerifyResult | None:
    """Queue a verification for each of the run's finished comparisons that ``which`` picks (V4)."""
    from compose_api.sedml import verifications  # late: verifications imports the service

    db = get_required_database_service().get_comparisons_db()
    if not any(r.number == number for r in await db.suite_runs(suite.name)):
        return None
    result = SuiteVerifyResult(queued=[], already=[], running=0)
    found = await db.suite_comparisons(suite.name, number)
    statuses = await service.member_statuses(found)
    for row in found:
        c = await service.comparison_view(row, statuses)
        if c.status == "running":
            result.running += 1
            continue
        if which == "failing" and not verifications.needs_verification(c):
            continue
        full = await db.get(c.comparison_id)
        _, created = await verifications.queue(full or row)
        (result.queued if created else result.already).append(c.comparison_id)
    return result


def _problems_for(suite: Suite, known: list[KnownProblem], number: int) -> dict[tuple[str, str | None], str]:
    """The known problems that apply to run ``number`` (docs/plan-known-problems.md, K2): those not cleared, or cleared
    by a later run; by (source, solver), each one's reason. The suite file's ``expected:`` entries count as open
    problems until they are moved to records (K8)."""
    applies: dict[tuple[str, str | None], str] = {(e.source, e.solver): e.reason for e in suite.expected}
    for p in known:
        if p.cleared_run is None or p.cleared_run > number:
            applies[(p.source, p.solver)] = p.reason
    return applies


def _pairs(result: dict[str, Any] | None) -> list[tuple[set[str], bool]]:
    """Every solver pair's verdict on every label, references left out: (the two solvers, close). A label neither
    solver of a pair reports (often a reaction rate the SED-ML asks for) says nothing about whether they agree, so it
    is left out too; one that only one of them reports counts against them."""
    pairs = []
    for report in ((result or {}).get("reports") or {}).values():
        for by_pair in (report.get("labels") or {}).values():
            for pair, verdict in by_pair.items():
                solvers = set(pair.split("|"))
                if verdict.get("reference") or solvers <= set(verdict.get("missing") or []):
                    continue
                pairs.append((solvers, verdict.get("close") is True))
    return pairs


def judge(
    close: bool | None, members: Mapping[str, str | None], result: dict[str, Any] | None, known: set[str]
) -> tuple[bool, list[str]]:
    """A finished row's standing against its solvers' known problems (docs/plan-known-problems.md, K3 and K4): whether
    it is excused (it fails or differs, but every solver without a known problem completed and they agree with each
    other), and which solvers with a known problem completed and agree with every solver they were compared with
    (resolved: the problem no longer occurs)."""
    pairs = _pairs(result)
    resolved = sorted(
        s
        for s in known
        if members.get(s) == "completed"
        and any(s in pair for pair, _ in pairs)
        and all(ok for pair, ok in pairs if s in pair)
    )
    if close is True:
        return False, resolved
    others = {s: status for s, status in members.items() if s not in known}
    excused = all(status == "completed" for status in others.values()) and all(
        ok for pair, ok in pairs if not pair & known
    )
    return excused, resolved


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
