"""SED-ML runs: an archive translated once per solver (translator.py), each accepted task and solver submitted as a
labelled run carrying the original archive, grouped by a comparison computed when its members have finished
(docs/plan-sedml.md, phase 3)."""

import datetime
import logging
import shutil
import tempfile
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
from compose_api.registry.solvers import Solver, load_solvers
from compose_api.registry.validation import AddressPolicy, validate_submission
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
) -> list[int]:
    """One comparison per accepted task (all, or those named), one run per solver that accepted it; the ids."""
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
        )
        for solver_id, archive in task.archives.items():
            run_dir = Path(tempfile.mkdtemp(prefix="sedml-run-"))
            input_file = run_dir / f"{task.name}.{solver_id}.omex"
            source_file = run_dir / "source.omex"
            shutil.copyfile(archive, input_file)
            shutil.copyfile(source, source_file)
            # the same check as any upload: the translation's addresses must be registered at `tested`
            validate_submission(input_file, SimulationFileType.OMEX, AddressPolicy(get_settings().address_policy))
            request = SimulationRequest(
                request_file_path=input_file,
                simulation_file_type=SimulationFileType.OMEX,
                is_batch=False,
                end_time_point=1.0,
                labels=labels(
                    source=source_kind or "upload",
                    environment=by_id[solver_id].environment,
                    solver=solver_id,
                    sedml_task=task.task,
                    comparison=str(comparison_id),
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
            )
            await db.get_comparisons_db().add_member(comparison_id, experiment.simulation_database_id, solver_id)
        created.append(comparison_id)
    return created


async def comparison_view(row: ComparisonRow) -> Comparison:
    """The comparison with its members' states; computed and stored once every member has finished."""
    db = get_required_database_service()
    members: list[ComparisonMember] = []
    for m in row.members:
        sim = await db.get_simulator_db().get_simulation_row(m.simulation_id)
        status = None
        if sim is not None:
            status = sim.run.status.to_job_status().value if sim.run is not None else "submitting"
        members.append(ComparisonMember(solver=m.solver, simulation_id=m.simulation_id, status=status))
    c = row.comparison
    status, result = c.status, c.result
    if status == "running" and members and all(m.status in TERMINAL for m in members):
        result = await _compute(c.settings, row)
        status = "complete" if all(m.status == "completed" for m in members) else "incomplete"
        await db.get_comparisons_db().set_result(c.id, status, result)
    return Comparison(
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


async def _compute(settings: dict[str, object], row: ComparisonRow) -> dict[str, object]:
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
    labels_by_report = {r: list(info.get("labels", [])) for r, info in report_files.items()}  # type: ignore[call-overload]
    result = compare(reports, labels_by_report, Tolerances.model_validate(settings.get("tolerances", {})))
    result["missing_reports"] = missing
    return result


def _iso(value: datetime.datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=datetime.UTC)
    return aware.astimezone(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def findings_for(translation: Translation, task: str | None = None) -> list[SedmlFinding]:
    return [f for f in translation.findings if task is None or f.task in (None, task)]
