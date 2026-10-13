"""SED-ML archives run as process-bigraph documents on several solvers (docs/plan-sedml.md, phase 3).

`/sedml/preview` translates an archive and says what each solver would run; `/sedml/run` submits one run per task and
accepted solver, each carrying the original archive (the `sedml-omex` dataset), grouped by a comparison
(`/comparisons`)."""

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile

from compose_api.authentication import OptionalPrincipal, describe_caller, get_optional_principal
from compose_api.common.gateway.models import RouterConfig
from compose_api.dependencies import get_required_database_service
from compose_api.registry.solvers import Solver
from compose_api.registry.validation import SubmissionRejectedError
from compose_api.sedml import service
from compose_api.sedml.models import SedmlPreview, SedmlRunResult, SedmlTask, Tolerances
from compose_api.sedml.translator import Translation, TranslatorUnavailableError
from compose_api.simulation.labels import LabelError, clean_description, clean_tags

logger = logging.getLogger(__name__)

config = RouterConfig(router=APIRouter(), prefix="/sedml", dependencies=[Depends(get_optional_principal)])

MAX_ARCHIVE = 100 * 1024 * 1024
Solvers = Annotated[list[str] | None, Query(description="Solvers to run (registry/solvers.yaml); all when omitted")]


async def _saved(upload: UploadFile) -> Path:
    """The upload as a temporary file; 400 unless it is a COMBINE/OMEX archive."""
    tmp = Path(tempfile.mkdtemp(prefix="sedml-upload-")) / Path(upload.filename or "source.omex").name
    with tmp.open("wb") as f:
        shutil.copyfileobj(upload.file, f, length=1024 * 1024)
    if tmp.stat().st_size == 0 or tmp.stat().st_size > MAX_ARCHIVE:
        raise HTTPException(status_code=400, detail="the archive is empty or larger than 100 MB")
    if not zipfile.is_zipfile(tmp):
        raise HTTPException(
            status_code=400, detail="expected a COMBINE/OMEX archive (a zip) holding SED-ML and its models"
        )
    return tmp


async def _translate(source: Path, solver_ids: list[str] | None) -> tuple[Translation, list[Solver]]:
    try:
        solvers = service.chosen_solvers(solver_ids)
        return await service.translate_upload(source, solvers), solvers
    except service.SolverUnknownError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except TranslatorUnavailableError as e:
        logger.exception("SED-ML translation is not available")
        raise HTTPException(status_code=503, detail="SED-ML translation is not available on this deployment") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _tasks(translation: Translation, solvers: list[Solver]) -> list[SedmlTask]:
    return [
        SedmlTask(
            sedml=t.sedml,
            task=t.task,
            name=t.name,
            template=t.template,
            solvers=list(t.archives),
            refused=[s.id for s in solvers if s.id not in t.archives],
            reports=list(t.reports),
        )
        for t in translation.tasks
    ]


@config.router.post(
    path="/preview",
    response_model=SedmlPreview,
    operation_id="preview-sedml",
    tags=["SED-ML"],
    summary="Translate a SED-ML archive without running it: its tasks, and what each solver would run or why not",
)
async def preview_sedml(archive: UploadFile, principal: OptionalPrincipal, solvers: Solvers = None) -> SedmlPreview:
    source = await _saved(archive)
    translation, chosen = await _translate(source, solvers)
    return SedmlPreview(source=translation.source, tasks=_tasks(translation, chosen), findings=translation.findings)


@config.router.post(
    path="/run",
    response_model=SedmlRunResult,
    operation_id="run-sedml",
    tags=["SED-ML"],
    summary="Run each task of a SED-ML archive on several solvers, one run per solver, grouped by a comparison",
    responses={400: {"description": "Not an archive, an unknown solver, a bad tag, or no task any solver accepted"}},
)
async def run_sedml(
    background_tasks: BackgroundTasks,
    archive: UploadFile,
    principal: OptionalPrincipal,
    solvers: Solvers = None,
    task: Annotated[list[str] | None, Query(description="Only these SED-ML task ids; all when omitted")] = None,
    tags: Annotated[list[str] | None, Query(description="Tags for every run")] = None,
    description: str | None = None,
    rel_tol: Annotated[float, Query(gt=0)] = Tolerances().rel_tol,
    abs_tol_min: Annotated[float, Query(ge=0)] = Tolerances().abs_tol_min,
    abs_tol_scale: Annotated[float, Query(ge=0)] = Tolerances().abs_tol_scale,
) -> SedmlRunResult:
    logger.info("SED-ML submission from %s", describe_caller(principal))
    try:
        run_tags, run_description = clean_tags(tags), clean_description(description)
    except LabelError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    source = await _saved(archive)
    translation, chosen = await _translate(source, solvers)
    tolerances = Tolerances(rel_tol=rel_tol, abs_tol_min=abs_tol_min, abs_tol_scale=abs_tol_scale)
    try:
        ids = await service.submit(
            translation, source, f"upload:{translation.source}", chosen, task, run_tags, run_description, tolerances,
            background_tasks,
        )  # fmt: skip
    except SubmissionRejectedError as e:
        raise HTTPException(
            status_code=400, detail={"message": e.message, "violations": [v.model_dump() for v in e.violations]}
        ) from e
    if not ids:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "no task was accepted by any solver",
                "findings": [f.model_dump() for f in translation.findings],
            },
        )
    db = get_required_database_service()
    comparisons = []
    for comparison_id in ids:
        row = await db.get_comparisons_db().get(comparison_id)
        if row is not None:
            comparisons.append(await service.comparison_view(row))
    return SedmlRunResult(comparisons=comparisons, findings=translation.findings)
