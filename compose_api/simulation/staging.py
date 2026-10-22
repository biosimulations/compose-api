"""Staging a queued run's files before the request returns (docs/plan-durable-submission.md, Q1).

An upload used to live in a pod-local temporary file until a background task copied it to the cluster, so a restart
lost it with the task. Now the request copies it, and a SED-ML run's original archive, to a staging directory and
records their paths in the run's submission; the worker reads them from there whenever it gets to the run.

Where the API sees the store (production), the staging directory is on the store: ``<namespace>/staging/<experiment
id>/``, written world-readable by the API's user, and copied into the experiment directory on the cluster at dispatch.
The experiment directory itself is left to the SLURM service user, who must write the run's outputs and events there.
Elsewhere (development, tests) the files go to ``settings.submission_staging_dir`` and are uploaded with scp.
"""

import logging
import shutil
from pathlib import Path

from compose_api.config import get_settings
from compose_api.simulation import images
from compose_api.simulation.hpc_utils import get_slurm_staging_dir
from compose_api.simulation.job_script import SOURCE_FILE_NAME
from compose_api.simulation.models import SimulationRequest

logger = logging.getLogger(__name__)

FILE_MODE = 0o644
DIR_MODE = 0o755


def stage_request(request: SimulationRequest, experiment_id: str) -> tuple[SimulationRequest, bool]:
    """Copy the request's files to the run's staging directory: the request with its paths pointing there (the
    cluster's view of them when on the store), and whether they are on the store.

    If the store refuses the write (its permissions), the files are staged locally instead, as before the queue: the
    run is still accepted and submitted, but a restart before dispatch loses its files."""
    mounted = images.internal_path(str(get_slurm_staging_dir(experiment_id)))
    if mounted is not None:
        try:
            return _stage(request, experiment_id, mounted, on_store=True), True
        except OSError:
            logger.exception(f"Could not stage {experiment_id} on the store; staging it locally instead")
            shutil.rmtree(mounted, ignore_errors=True)
    local = Path(get_settings().submission_staging_dir) / experiment_id
    return _stage(request, experiment_id, local, on_store=False), False


def _stage(request: SimulationRequest, experiment_id: str, target: Path, *, on_store: bool) -> SimulationRequest:
    on_store_dir = get_slurm_staging_dir(experiment_id)
    _make_dir(target)

    def place(source: Path, name: str) -> Path:
        staged = target / name
        shutil.copyfile(source, staged)
        staged.chmod(FILE_MODE)
        return on_store_dir / name if on_store else staged

    suffix = request.simulation_file_type.get_files_suffix()
    input_path = place(request.request_file_path, f"{experiment_id}.{suffix}")
    source_path = place(request.source_file_path, SOURCE_FILE_NAME) if request.source_file_path is not None else None
    return request.model_copy(update={"request_file_path": input_path, "source_file_path": source_path})


def local_staging_dir(experiment_id: str, staged_on_store: bool) -> Path | None:
    """The API's own view of a run's staging directory, to remove it once the run is on the cluster."""
    if staged_on_store:
        return images.internal_path(str(get_slurm_staging_dir(experiment_id)))
    return Path(get_settings().submission_staging_dir) / experiment_id


def remove_staging(experiment_id: str, staged_on_store: bool) -> None:
    """Best effort: the experiment directory holds the run's copy of the input from here on."""
    directory = local_staging_dir(experiment_id, staged_on_store)
    if directory is not None:
        shutil.rmtree(directory, ignore_errors=True)


def _make_dir(directory: Path) -> None:
    created = [p for p in (directory, *directory.parents) if not p.exists()]
    directory.mkdir(parents=True, exist_ok=True)
    for path in created:
        path.chmod(DIR_MODE)  # readable and traversable by the SLURM service user, whatever the API's umask
