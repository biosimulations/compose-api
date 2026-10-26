"""SED-ML runs: an archive translated once per solver (translator.py), each accepted task and solver submitted as a
labelled run carrying the original archive, grouped by a comparison computed when its members have finished
(docs/plan-sedml.md, phase 3)."""

import datetime
import logging
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from fastapi import BackgroundTasks

from compose_api.common.gateway.models import Namespace
from compose_api.config import get_settings
from compose_api.db.services.comparisons_db import ComparisonRow
from compose_api.dependencies import (
    get_required_database_service,
    get_required_job_monitor,
    get_required_simulation_service,
)
from compose_api.environments.admission import standing_for
from compose_api.registry.solvers import Solver, load_solvers
from compose_api.registry.validation import AddressPolicy, Standing, validate_submission
from compose_api.sedml.compare import compare, read_report
from compose_api.sedml.models import Comparison, ComparisonMember, SedmlFinding, Tolerances
from compose_api.sedml.translator import Translation, translate
from compose_api.simulation.handlers import run_simulation
from compose_api.simulation.hpc_utils import get_internal_experiment_dir
from compose_api.simulation.labels import labels
from compose_api.simulation.models import SimulationFileType, SimulationRequest

logger = logging.getLogger(__name__)

#: A member in one of these states has finished; the comparison is computed when every member has.
TERMINAL = {"completed", "failed", "cancelled", "out_of_memory", "timeout"}


class SolverUnknownError(ValueError):
    pass


def chosen_solvers(ids: list[str] | None) -> list[Solver]:
    """The solvers asked for, or every solver; `SolverUnknownError` for one registry/solvers.yaml lacks."""
    all_solvers = {s.id: s for s in load_solvers().solvers}
    if not ids:
        return list(all_solvers.values())
    unknown = sorted(set(ids) - set(all_solvers))
    if unknown:
        raise SolverUnknownError(f"no solver {', '.join(unknown)}; there are {', '.join(all_solvers)}")
    return [all_solvers[i] for i in dict.fromkeys(ids)]


async def translate_upload(source: Path, solvers: list[Solver]) -> Translation:
    workdir = Path(tempfile.mkdtemp(prefix="sedml-"))
    return await translate(source, solvers, workdir)


async def submit(
    translation: Translation,
    source: Path,
    source_label: str,
    solvers: list[Solver],
    tasks: list[str] | None,
    tags: list[str],
    description: str | None,
    tolerances: Tolerances,
    background_tasks: BackgroundTasks,
    references: dict[str, dict[str, dict[str, list[float]]]] | None = None,
    collection: str | None = None,
    suite_run: int | None = None,
    queue: str = "interactive",
    priority: int = 0,
    batch: bool = False,
    environment_versions: dict[str, int] | None = None,
) -> list[int]:
    """One comparison per accepted task (all, or those named), one run per solver that accepted it; the ids.
    `references[origin]["<sedml>/<report>"]` (the archive's own `reports.h5`, a biosimulations.org run's) are stored
    with the comparison of the task whose SED-ML and report they match."""
    references = {**archive_references(source), **(references or {})}
    db = get_required_database_service()
    by_id = {s.id: s for s in solvers}
    source_kind, _, source_id = source_label.partition(":")
    extra = (
        {"model": source_id}
        if source_kind == "biomodels"
        else {"project": source_id}
        if source_kind == "biosimulations"
        else {}
    )
    created: list[int] = []
    standings: dict[str, Standing | None] = {}  # the version each solver's environment will run, by environment
    for task in translation.tasks:
        if tasks and task.task not in tasks:
            continue
        if not task.archives:
            continue
        comparison_id = await db.get_comparisons_db().insert(
            name=f"{translation.source} {task.task}",
            source=source_label,
            sedml=task.sedml,
            task=task.task,
            settings={
                "tolerances": tolerances.model_dump(),
                "reports": task.reports,
                "solvers": list(task.archives),
            },
            collection=collection,
            suite_run=suite_run,
        )
        for origin, by_output in references.items():
            matched = match_references(task.sedml, task.reports, by_output)
            if matched:
                await db.get_comparisons_db().add_reference(comparison_id, origin, matched)
        for solver_id, archive in task.archives.items():
            run_dir = Path(tempfile.mkdtemp(prefix="sedml-run-"))
            input_file = run_dir / f"{task.name}.{solver_id}.omex"
            source_file = run_dir / "source.omex"
            shutil.copyfile(archive, input_file)
            shutil.copyfile(source, source_file)
            # the same check as any upload: the translation's addresses must be registered at `tested`, and not
            # refused by the version the solver's environment will run (docs/plan-environment-composition.md, 5c)
            environment = by_id[solver_id].environment
            if environment not in standings:
                number = (environment_versions or {}).get(environment)
                standings[environment] = await standing_for(db, environment, number)
            validate_submission(
                input_file,
                SimulationFileType.OMEX,
                AddressPolicy(get_settings().address_policy),
                standing=standings[environment],
            )
            request = SimulationRequest(
                request_file_path=input_file,
                simulation_file_type=SimulationFileType.OMEX,
                # a suite's runs are queued behind interactive ones, with the batch resources (Q3, Q4)
                is_batch=batch,
                end_time_point=1.0,
                # the version named for the solver's environment (docs/plan-environment-versions.md); else its default.
                # Every solver runs in the shared environment today (registry/solvers.yaml), which a request without a
                # `simulator` names; a solver in a prebuilt one would need its `simulator` set here too.
                environment_version=(environment_versions or {}).get(by_id[solver_id].environment),
                labels=labels(
                    source=source_kind or "upload",
                    environment=by_id[solver_id].environment,
                    solver=solver_id,
                    sedml_task=task.task,
                    comparison=str(comparison_id),
                    collection=collection,
                    suite_run=str(suite_run) if suite_run is not None else None,
                    **extra,
                ),
                tags=tags,
                description=description,
                source_file_path=source_file,
            )
            experiment = await run_simulation(
                simulation_request=request,
                database_service=db,
                simulation_service_slurm=get_required_simulation_service(),
                background_tasks=background_tasks,
                job_monitor=get_required_job_monitor(),
                queue=queue,
                priority=priority,
            )
            await db.get_comparisons_db().add_member(comparison_id, experiment.simulation_database_id, solver_id)
        created.append(comparison_id)
    return created


def match_references(
    sedml: str, report_ids: Iterable[str], by_output: Mapping[str, dict[str, list[float]]]
) -> dict[str, dict[str, list[float]]]:
    """A reference's outputs (``{"<sedml>/<output>": {label: series}}``) for the task's reports, by report id."""
    return {r: by_output[f"{sedml}/{r}"] for r in report_ids if f"{sedml}/{r}" in by_output}


async def recompute(comparison_id: int) -> None:
    """Score a finished comparison again, after a reference was added (the verify oracle, docs/plan-verify-oracle.md
    V3). One still running is scored when its members finish, with every reference it has by then."""
    db = get_required_database_service()
    row = await db.get_comparisons_db().get(comparison_id)
    if row is None or row.comparison.status == "running":
        return
    result = await _compute(row.comparison.settings, row)
    await db.get_comparisons_db().set_result(comparison_id, row.comparison.status, result)


async def member_statuses(rows: Iterable[ComparisonRow]) -> dict[int, str]:
    """Every member's status across ``rows``, in one query (a suite run has hundreds of members)."""
    ids = sorted({m.simulation_id for row in rows for m in row.members})
    return await get_required_database_service().get_simulator_db().get_simulation_statuses(ids)


async def comparison_view(row: ComparisonRow, statuses: Mapping[int, str] | None = None) -> Comparison:
    """The comparison with its members' states; computed and stored once every member has finished. ``statuses``
    (from `member_statuses`) saves a query per member when viewing many comparisons."""
    db = get_required_database_service()
    if statuses is None:
        statuses = await member_statuses([row])
    members = [
        ComparisonMember(solver=m.solver, simulation_id=m.simulation_id, status=statuses.get(m.simulation_id))
        for m in row.members
    ]
    c = row.comparison
    status, result = c.status, c.result
    if status == "running" and members and all(m.status in TERMINAL for m in members):
        full = await db.get_comparisons_db().get(c.id)  # a page's rows carry no references
        result = await _compute(c.settings, full or row)
        status = "complete" if all(m.status == "completed" for m in members) else "incomplete"
        await db.get_comparisons_db().set_result(c.id, status, result)
        just_finished = True
    else:
        just_finished = False
    view = Comparison(
        comparison_id=c.id,
        created_at=_iso(c.created_at),
        name=c.name,
        source=c.source,
        sedml=c.sedml,
        task=c.task,
        status=status,  # type: ignore[arg-type]
        settings=c.settings,
        members=members,
        result=result,
        close=None if result is None else bool(result.get("close")) and status == "complete",
    )
    if just_finished and c.collection:
        await _verify_by_suite(row, view)
    return view


async def _verify_by_suite(row: ComparisonRow, comparison: Comparison) -> None:
    """A suite's `verify` option (docs/plan-verify-oracle.md, V4), applied as each of its comparisons finishes."""
    from compose_api.sedml import suites, verifications  # late: verifications imports this module

    found = suites.suite(row.comparison.collection or "")
    if found is None or found.verify == "none":
        return
    if found.verify == "all" or verifications.needs_verification(comparison):
        try:
            await verifications.queue(row)
        except Exception:  # evidence, never a reason to fail reading the comparison
            logger.exception(f"comparison {comparison.comparison_id}: could not queue its verification")


async def member_reports(
    settings: dict[str, object], row: ComparisonRow
) -> tuple[dict[str, dict[str, dict[str, list[float]]]], dict[str, list[str]]]:
    """Each member's report CSVs, read from its experiment directory: `{solver: {report: {label: series}}}`, and the
    reports each member lacks."""
    db = get_required_database_service()
    namespace = Namespace(get_settings().namespace)
    report_files: dict[str, dict[str, object]] = settings.get("reports", {})  # type: ignore[assignment]
    reports: dict[str, dict[str, dict[str, list[float]]]] = {}
    missing: dict[str, list[str]] = {}
    for m in row.members:
        experiment_id = await db.get_simulator_db().get_simulations_experiment_id(simulation_id=m.simulation_id)
        root = get_internal_experiment_dir(experiment_id, namespace)
        reports[m.solver] = {}
        for report_id, info in report_files.items():
            path = root / str(info["file"])
            try:
                reports[m.solver][report_id] = read_report(path.read_text(encoding="utf-8"))
            except OSError:
                missing.setdefault(m.solver, []).append(report_id)
    return reports, missing


async def _compute(settings: dict[str, object], row: ComparisonRow) -> dict[str, object]:
    report_files: dict[str, dict[str, object]] = settings.get("reports", {})  # type: ignore[assignment]
    reports, missing = await member_reports(settings, row)
    labels_by_report = {r: list(info.get("labels", [])) for r, info in report_files.items()}  # type: ignore[call-overload]
    references = {ref.origin: ref.reports for ref in row.references}
    result = compare(
        reports, labels_by_report, Tolerances.model_validate(settings.get("tolerances", {})), references=references
    )
    result["missing_reports"] = missing
    return result


def _iso(value: datetime.datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=datetime.UTC)
    return aware.astimezone(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def archive_references(source: Path) -> dict[str, dict[str, dict[str, list[float]]]]:
    """Results shipped in the archive (`reports.h5`, as biosimulations.org projects carry them), as a reference."""
    import zipfile

    from compose_api.sedml.sources import reports_from_h5

    try:
        with zipfile.ZipFile(source) as z:
            name = next((n for n in z.namelist() if n.rsplit("/", 1)[-1] == "reports.h5"), None)
            if name is None:
                return {}
            reports = reports_from_h5(z.read(name))
    except (OSError, zipfile.BadZipFile, ValueError):
        logger.warning("could not read the reports.h5 in %s", source.name)
        return {}
    return {"archive": reports} if reports else {}


def findings_for(translation: Translation, task: str | None = None) -> list[SedmlFinding]:
    return [f for f in translation.findings if task is None or f.task in (None, task)]
