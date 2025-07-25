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
    slurm_log_remote_path = Path(settings.slurm_log_base_path)
    return slurm_log_remote_path / f"{slurm_job_name}.out"


def get_slurm_submit_file(slurm_job_name: str) -> Path:
    settings = get_settings()
    slurm_log_remote_path = Path(settings.slurm_log_base_path)
    return slurm_log_remote_path / f"{slurm_job_name}.sbatch"


def get_experiment_path(simulation: Simulation) -> Path:
    settings = get_settings()
    sim_id = simulation.database_id
    git_commit_hash = simulation.sim_request.simulator.git_commit_hash
    experiment_dirname = f"experiment_{git_commit_hash}_id_{sim_id}"
    return Path(settings.hpc_sim_base_path) / experiment_dirname


def get_correlation_id(simulation: Simulation, random_string: str) -> str:
    """
    Generate a correlation ID for the Simulation based on its database ID and git commit hash.
    """
    return f"{simulation.database_id}_{simulation.sim_request.simulator.git_commit_hash}_{random_string}"


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
    return hpc_image_remote_path / f"simulator-{simulator_version.git_commit_hash}.sif"


def get_experiment_dirname(database_id: int, git_commit_hash: str) -> str:
    return f"experiment_{git_commit_hash}_id_{database_id}"


def format_experiment_path(experiment_dirname: str, namespace: Namespace = Namespace.TEST) -> Path:
    base_path = f"/home/FCAM/crbmapi/compose_api/{namespace}/sims"
    return Path(base_path) / experiment_dirname


def get_experiment_dirpath(
    simulation_database_id: int, git_commit_hash: str, namespace: Namespace | None = None
) -> Path:
    experiment_dirname = get_experiment_dirname(database_id=simulation_database_id, git_commit_hash=git_commit_hash)
    return format_experiment_path(experiment_dirname=experiment_dirname, namespace=namespace or Namespace.TEST)


def get_remote_chunks_dirpath(
    simulation_database_id: int, git_commit_hash: str, namespace: Namespace | None = None
) -> Path:
    remote_dir_root = get_experiment_dirpath(
        simulation_database_id=simulation_database_id, git_commit_hash=git_commit_hash, namespace=namespace
    )
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
    return (
        router_config.prefix.replace("/", "")
        + "_"
        + get_experiment_dirname(simulation.database_id, sim_request.simulator.git_commit_hash)
    )
