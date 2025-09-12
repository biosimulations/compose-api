import hashlib
from pathlib import Path

from compose_api.btools.bsander.bsandr_utils.input_types import ContainerizationFileRepr
from compose_api.common.gateway.models import Namespace
from compose_api.config import get_settings
from compose_api.simulation.models import (
    JobType,
    SimulatorVersion,
)


def get_slurm_log_file(slurm_job_name: str) -> Path:
    settings = get_settings()
    return Path(settings.slurm_log_base_path) / f"{slurm_job_name}.out"


def get_slurm_submit_file(slurm_job_name: str) -> Path:
    settings = get_settings()
    return Path(settings.slurm_sbatch_base_path) / f"{slurm_job_name}.sbatch"


def get_slurm_singularity_def_file(singularity_hash: str) -> Path:
    settings = get_settings()
    return Path(settings.hpc_image_base_path) / f"{singularity_hash}.def"


def get_slurm_singularity_container_file(singularity_hash: str) -> Path:
    settings = get_settings()
    return Path(settings.hpc_image_base_path) / f"{singularity_hash}.sif"


def get_slurm_sim_input_file_path(experiment_id: str) -> Path:
    return get_slurm_sim_experiment_dir(experiment_id) / f"{experiment_id}.omex"


def get_slurm_sim_output_directory_path(experiment_id: str) -> Path:
    return get_slurm_sim_experiment_dir(experiment_id) / "output"


def get_slurm_sim_results_file_path(experiment_id: str) -> Path:
    return get_slurm_sim_experiment_dir(experiment_id) / "results.zip"


def get_slurm_sim_experiment_dir(experiment_id: str) -> Path:
    settings = get_settings()
    return Path(settings.hpc_sim_base_path) / f"experiment-{experiment_id}"


def get_slurm_job_name(experiment_id: str) -> str:
    """
    Create a human-readable job name .
    """
    return f"{experiment_id}"


def get_correlation_id(random_string: str, job_type: JobType) -> str:
    """
    Generate a correlation ID for the Simulation based on its database ID and random string.
    """
    return f"{job_type.value}-{random_string}"


def get_apptainer_image_file(simulator_version: SimulatorVersion) -> Path:
    settings = get_settings()
    hpc_image_remote_path = Path(settings.hpc_image_base_path)
    return hpc_image_remote_path / f"simulator-{simulator_version.singularity_def_hash}.sif"


def format_experiment_path(experiment_dirname: str, namespace: Namespace = Namespace.TEST) -> Path:
    base_path = f"/home/FCAM/crbmapi/compose_api/{namespace}/sims"
    return Path(base_path) / experiment_dirname


def get_experiment_id(simulator: SimulatorVersion, random_str: str) -> str:
    return f"{simulator.singularity_def_hash}_{random_str}"


def get_singularity_hash(singularity_def_rep: ContainerizationFileRepr) -> str:
    return hashlib.md5(singularity_def_rep.representation.encode("utf-8")).hexdigest()  # noqa: S324
