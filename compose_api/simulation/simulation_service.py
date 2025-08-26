import logging
import random
import string
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from textwrap import dedent

from bsander.bsandr_utils.input_types import (  # type: ignore[import-untyped]
    ContainerizationEngine,
    ContainerizationTypes,
    ProgramArguments,
)
from bsander.execution import execute_bsander  # type: ignore[import-untyped]
from typing_extensions import override

from compose_api.common.hpc.models import SlurmJob
from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.common.ssh.ssh_service import SSHService
from compose_api.config import get_settings
from compose_api.simulation.database_service import DatabaseService
from compose_api.simulation.hpc_utils import (
    get_experiment_path,
    get_slurm_log_file,
    get_slurm_sim_experiment_dir,
    get_slurm_sim_input_file,
    get_slurm_singularity_def_file,
    get_slurm_submit_file,
)
from compose_api.simulation.models import Simulation, SimulatorVersion

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
        slurm_job_name = f"sim-{simulation.database_id}-{random_suffix}"

        slurm_log_file = get_slurm_log_file(slurm_job_name=slurm_job_name)
        slurm_submit_file = get_slurm_submit_file(slurm_job_name=slurm_job_name)
        slurm_singularity_file = get_slurm_singularity_def_file(slurm_job_name=slurm_job_name)
        slurm_input_file = get_slurm_sim_input_file(slurm_job_name=slurm_job_name)
        experiment_path = get_experiment_path(simulation=simulation)

        # build the submit script
        with tempfile.TemporaryDirectory() as tmpdir:
            local_singularity_file = tmpdir + "/singularity.def"
            execute_bsander(
                ProgramArguments(
                    input_file_path=str(simulation.omex_archive),
                    output_dir=tmpdir,
                    containerization_type=ContainerizationTypes.SINGLE,
                    containerization_engine=ContainerizationEngine.APPTAINER,
                )
            )
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

                    # singularity build sim-{slurm_job_name}.sif {slurm_singularity_file}
                    echo "Simulation {slurm_job_name} running."
                    singularity exec \
                        --bind {get_slurm_sim_experiment_dir(slurm_job_name)}:/experiment \
                        {settings.hpc_image_base_path}/test.sif \
                         python3 /runtime/main.py /experiment/{slurm_job_name}.omex
                    echo "Simulation run completed. data saved to {experiment_path!s}."
                    """)
                f.write(script_content)

            await ssh_service.run_command(f"mkdir {get_slurm_sim_experiment_dir(slurm_job_name)}")
            # submit the build script to slurm
            slurm_jobid = await slurm_service.submit_job(
                local_sbatch_file=local_submit_file,
                remote_sbatch_file=slurm_submit_file,
                local_input_file=simulation.omex_archive or Path(""),
                remote_input_file=slurm_input_file,
                local_singularity_file=Path(local_singularity_file),
                remote_singularity_file=slurm_singularity_file,
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
