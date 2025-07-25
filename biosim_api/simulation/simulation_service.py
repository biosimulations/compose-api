import logging
import random
import string
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from textwrap import dedent

from typing_extensions import override

from biosim_api.common.hpc.models import SlurmJob
from biosim_api.common.hpc.slurm_service import SlurmService
from biosim_api.common.ssh.ssh_service import SSHService
from biosim_api.config import get_settings
from biosim_api.simulation.database_service import DatabaseService
from biosim_api.simulation.hpc_utils import (
    get_experiment_path,
    get_slurm_log_file,
    get_slurm_submit_file,
)
from biosim_api.simulation.models import Simulation, SimulatorVersion

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SimulationService(ABC):
    @abstractmethod
    async def submit_simulation_job(
        self,
        simulation: Simulation,
        simulator_version: SimulatorVersion,
        database_service: DatabaseService,
        correlation_id: str,
    ) -> int:
        pass

    @abstractmethod
    async def get_slurm_job_status(self, slurmjobid: int) -> SlurmJob | None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class SimulationServiceHpc(SimulationService):
    _latest_commit_hash: str | None = None

    @override
    async def submit_simulation_job(
        self,
        simulation: Simulation,
        simulator_version: SimulatorVersion,
        database_service: DatabaseService,
        correlation_id: str,
    ) -> int:
        settings = get_settings()
        ssh_service = SSHService(
            hostname=settings.slurm_submit_host,
            username=settings.slurm_submit_user,
            key_path=Path(settings.slurm_submit_key_path),
            known_hosts=Path(settings.slurm_submit_known_hosts) if settings.slurm_submit_known_hosts else None,
        )
        if database_service is None:
            raise RuntimeError("DatabaseService is not available. Cannot submit Simulation job.")

        if simulation.sim_request is None:
            raise ValueError("Simulation must have a sim_request set to submit a job.")

        slurm_service = SlurmService(ssh_service=ssh_service)

        random_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))  # noqa: S311
        slurm_job_name = f"sim-{simulator_version.git_commit_hash}-{simulation.database_id}-{random_suffix}"

        slurm_log_file = get_slurm_log_file(slurm_job_name=slurm_job_name)
        slurm_submit_file = get_slurm_submit_file(slurm_job_name=slurm_job_name)
        experiment_path = get_experiment_path(simulation=simulation)
        experiment_path_parent = experiment_path.parent

        # build the submit script
        with tempfile.TemporaryDirectory() as tmpdir:
            local_submit_file = Path(tmpdir) / f"{slurm_job_name}.sbatch"
            with open(local_submit_file, "w") as f:
                script_content = dedent(f"""\
                    #!/bin/bash
                    #SBATCH --job-name={slurm_job_name}
                    #SBATCH --time=30:00
                    #SBATCH --cpus-per-task 2
                    #SBATCH --mem=8GB
                    #SBATCH --partition={settings.slurm_partition}
                    #SBATCH --qos={settings.slurm_qos}
                    #SBATCH --output={slurm_log_file}
                    #SBATCH --nodelist={settings.slurm_node_list}

                    set -e
                    # env
                    mkdir -p {experiment_path_parent!s}

                    commit_hash="{simulator_version.git_commit_hash}"
                    sim_id="{simulation.database_id}"
                    echo "running simulation: commit=$commit_hash, simulation id=$sim_id on $(hostname) ..."

                    echo "Simulation run completed. data saved to {experiment_path!s}."
                    """)
                f.write(script_content)

            # submit the build script to slurm
            slurm_jobid = await slurm_service.submit_job(
                local_sbatch_file=local_submit_file, remote_sbatch_file=slurm_submit_file
            )
            return slurm_jobid

    @override
    async def get_slurm_job_status(self, slurmjobid: int) -> SlurmJob | None:
        settings = get_settings()
        ssh_service = SSHService(
            hostname=settings.slurm_submit_host,
            username=settings.slurm_submit_user,
            key_path=Path(settings.slurm_submit_key_path),
            known_hosts=Path(settings.slurm_submit_known_hosts) if settings.slurm_submit_known_hosts else None,
        )
        slurm_service = SlurmService(ssh_service=ssh_service)
        job_ids: list[SlurmJob] = await slurm_service.get_job_status_squeue(job_ids=[slurmjobid])
        if len(job_ids) == 0:
            job_ids = await slurm_service.get_job_status_sacct(job_ids=[slurmjobid])
            if len(job_ids) == 0:
                logger.warning(f"No job found with ID {slurmjobid} in both squeue and sacct.")
                return None
        if len(job_ids) == 1:
            return job_ids[0]
        else:
            raise RuntimeError(f"Multiple jobs found with ID {slurmjobid}: {job_ids}")

    @override
    async def close(self) -> None:
        pass
