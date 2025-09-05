import os
from pathlib import Path

from compose_api.common.gateway.models import Namespace, RouterConfig
from compose_api.config import get_settings
from compose_api.simulation.models import (
    Simulation,
    SimulationRequest,
    SimulatorVersion,
)


def get_slurm_log_file(slurm_job_name: str) -> Path:
    settings = get_settings()
    return Path(settings.slurm_log_base_path) / f"{slurm_job_name}.out"


def get_slurm_submit_file(slurm_job_name: str) -> Path:
    settings = get_settings()
    return Path(settings.hpc_image_base_path) / f"{slurm_job_name}.sbatch"


def get_slurm_singularity_def_file(slurm_job_name: str) -> Path:
    settings = get_settings()
    return Path(settings.hpc_image_base_path) / f"{slurm_job_name}.def"


def get_slurm_sim_input_file_path(slurm_job_name: str) -> Path:
    return get_slurm_sim_experiment_dir(slurm_job_name) / f"{slurm_job_name}.omex"


def get_slurm_sim_output_directory_path(slurm_job_name: str) -> Path:
    return get_slurm_sim_experiment_dir(slurm_job_name) / "output"


def get_slurm_sim_results_file_path(slurm_job_name: str) -> Path:
    return get_slurm_sim_experiment_dir(slurm_job_name) / "results.zip"


def get_slurm_sim_experiment_dir(slurm_job_name: str) -> Path:
    settings = get_settings()
    return Path(settings.hpc_image_base_path) / f"experiment-{slurm_job_name}"


def get_slurm_job_name(correlation_id: str) -> str:
    """
    Create a human-readable job name .
    """
    return f"{correlation_id}"


def get_correlation_id(random_string: str) -> str:
    """
    Generate a correlation ID for the Simulation based on its database ID and random string.
    """
    return f"{random_string}"


def parse_correlation_id(correlation_id: str) -> tuple[int, str, str]:
    """
    Extract the simulation database ID and git commit hash from the correlation ID.
    """
    parts = correlation_id.split("_")
    if len(parts) != 3:
        raise ValueError(f"Invalid correlation ID format: {correlation_id}")
    simulation_id = int(parts[0])
    simulator_commit_hash = parts[1]
    random_string = parts[2]
    return simulation_id, simulator_commit_hash, random_string


def get_apptainer_image_file(simulator_version: SimulatorVersion) -> Path:
    settings = get_settings()
    hpc_image_remote_path = Path(settings.hpc_image_base_path)
    return hpc_image_remote_path / f"simulator-{simulator_version.pb_cache_hash}.sif"


def format_experiment_path(experiment_dirname: str, namespace: Namespace = Namespace.TEST) -> Path:
    base_path = f"/home/FCAM/crbmapi/compose_api/{namespace}/sims"
    return Path(base_path) / experiment_dirname


def get_remote_chunks_dirpath(
    slurm_job_name: str,
) -> Path:
    remote_dir_root = get_slurm_sim_experiment_dir(slurm_job_name)
    experiment_dirname = str(remote_dir_root).split("/")[-1]
    return Path(
        os.path.join(
            remote_dir_root,
            "history",
            f"experiment_id={experiment_dirname}",
            "variant=0",
            "lineage_seed=0",
            "generation=1",
            "agent_id=0",
        )
    )


def get_experiment_id(router_config: RouterConfig, simulation: Simulation, sim_request: SimulationRequest) -> str:
    return router_config.prefix.replace("/", "") + "_"
