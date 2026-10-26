"""Running compliance (docs/plan-environment-composition.md, step 5b): each member entry's cases run in a composed
version once it is ready, through the run path like any document, and are evaluated as their runs finish.

``start`` submits them (after a build, or again on request); ``refresh`` evaluates the ones whose runs have finished,
reading each run's ``.pber`` from its experiment directory; ``report`` says where each entry stands in the version,
and which components the generic checks refuse there (``environments/compliance.py``). Evaluation happens when the
report is read, so nothing polls.
"""

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import BackgroundTasks

from compose_api.common.gateway.models import Namespace
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseService
from compose_api.environments import compliance, pixi
from compose_api.simulation.hpc_utils import get_internal_experiment_dir
from compose_api.simulation.labels import labels
from compose_api.simulation.models import (
    ComplianceCase,
    ComplianceReport,
    EntryCompliance,
    EnvironmentVersion,
    EnvironmentVersionDetail,
    SimulationFileType,
    SimulationRequest,
)

logger = logging.getLogger(__name__)

# a run that ended in one of these has nothing more to say
_FINISHED = {"completed", "failed", "cancelled", "out_of_memory", "timeout"}


def member_entries(version: EnvironmentVersion) -> list[str]:
    """The registry entries a composed version is made of, as its spec records them."""
    return [str(e["id"]) for e in (version.spec or {}).get("entries", []) if "id" in e]


def _archive(case: compliance.Case, directory: Path) -> Path:
    """The case as the runner takes it: an omex holding its document and the files it reads, by name."""
    archive = directory / f"{case.entry}.{case.name}.omex"
    with zipfile.ZipFile(archive, "w") as omex:
        for name in [case.document, *case.files]:
            omex.write(case.path(name), arcname=name)
    return archive


async def start(database_service: DatabaseService, version: EnvironmentVersion) -> int:
    """Submit every case of the version's entries to run in it: how many. A version that is not composed (its image
    is not run by compose-api's runner) has none."""
    from compose_api.dependencies import get_required_job_monitor, get_required_simulation_service
    from compose_api.simulation.handlers import run_simulation

    if version.runtime_contract != pixi.RUNTIME_CONTRACT:
        return 0
    jobs = BackgroundTasks()
    submitted = 0
    environments_db = database_service.get_environments_db()
    try:
        for entry in member_entries(version):
            for case in compliance.load_cases(entry):
                problems = compliance.case_problems(case)
                if problems:
                    logger.warning(f"compliance case {entry}/{case.name} cannot run: {problems}")
                    continue
                directory = Path(tempfile.mkdtemp(prefix="compliance-"))
                request = SimulationRequest(
                    request_file_path=_archive(case, directory),
                    simulation_file_type=SimulationFileType.OMEX,
                    end_time_point=case.interval,
                    is_batch=True,
                    environment_version=version.number,
                    labels=labels(
                        source="compliance", environment=version.environment, compliance=f"{entry}/{case.name}"
                    ),
                    description=f"compliance: {entry}/{case.name} in {version.label}",
                )
                experiment = await run_simulation(
                    simulation_request=request,
                    database_service=database_service,
                    simulation_service_slurm=get_required_simulation_service(),
                    background_tasks=jobs,
                    job_monitor=get_required_job_monitor(),
                    queue=f"compliance:{version.environment}",  # queued apart, behind interactive runs
                )
                await environments_db.add_compliance_run(
                    version.database_id, entry, case.name, experiment.simulation_database_id
                )
                shutil.rmtree(directory, ignore_errors=True)
                submitted += 1
    finally:
        await jobs()
    logger.info(f"{version.label}: {submitted} compliance cases submitted")
    return submitted


def _results(experiment_dir: Path) -> dict[str, object]:
    found = sorted((experiment_dir / "output").glob("results_*.pber"))
    if not found:
        raise FileNotFoundError("the run wrote no results (.pber)")
    return compliance.results_of(found[-1].read_text())


async def refresh(database_service: DatabaseService, version: EnvironmentVersion) -> None:
    """Evaluate every pending case whose run has finished."""
    environments_db = database_service.get_environments_db()
    simulators_db = database_service.get_simulator_db()
    pending = [r for r in await environments_db.compliance_runs(version.database_id) if r.state == "pending"]
    statuses = await simulators_db.get_simulation_statuses([r.simulation_id for r in pending if r.simulation_id])
    namespace = Namespace(get_settings().namespace)
    for run in pending:
        status = statuses.get(run.simulation_id) if run.simulation_id else "missing"
        if status not in _FINISHED and status != "missing":
            continue
        if status != "completed":
            await environments_db.set_compliance_outcome(run.id, "error", [f"the run ended {status}"])
            continue
        case = next((c for c in compliance.load_cases(run.entry) if c.name == run.case), None)
        if case is None:
            await environments_db.set_compliance_outcome(run.id, "error", ["the case no longer exists"])
            continue
        try:
            experiment_id = await simulators_db.get_simulations_experiment_id(simulation_id=run.simulation_id or 0)
            results = _results(get_internal_experiment_dir(experiment_id, namespace))
        except (OSError, ValueError) as e:
            await environments_db.set_compliance_outcome(run.id, "error", [f"its results could not be read: {e}"])
            continue
        outcome = compliance.evaluate(case, results)
        await environments_db.set_compliance_outcome(run.id, "passed" if outcome.passed else "failed", outcome.failures)


def _level(cases: list[ComplianceCase]) -> str:
    if not cases:
        return "untested"
    if any(c.state == "pending" for c in cases):
        return "pending"
    return "tested" if all(c.state == "passed" for c in cases) else "failed"


async def report(database_service: DatabaseService, version: EnvironmentVersionDetail) -> ComplianceReport:
    """Where each of the version's entries stands there, and which components the generic checks refuse."""
    runs = await database_service.get_environments_db().compliance_runs(version.database_id)
    entries = []
    for entry in member_entries(version) or sorted({r.entry for r in runs}):
        cases = [
            ComplianceCase(case=r.case, state=r.state, simulation_id=r.simulation_id, failures=r.failures)
            for r in runs
            if r.entry == entry
        ]
        entries.append(EntryCompliance(entry=entry, level=_level(cases), cases=cases))
    findings = list(version.findings or [])
    refused = sorted({str(f["component"]) for f in findings if f.get("severity") == "fail"})
    return ComplianceReport(
        environment=version.environment, number=version.number, entries=entries, findings=findings, refused=refused
    )
