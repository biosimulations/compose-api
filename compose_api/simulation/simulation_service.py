import logging
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from textwrap import dedent

from typing_extensions import override

from compose_api.btools.bsander.bsandr_utils.input_types import (
    ContainerizationEngine,
    ContainerizationTypes,
    ProgramArguments,
)
from compose_api.btools.bsander.execution import execute_bsander
from compose_api.common.hpc.models import SlurmJob
from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.common.ssh.ssh_service import SSHService, get_ssh_service
from compose_api.config import Settings, get_settings
from compose_api.db.database_service import DatabaseService
from compose_api.simulation.hpc_utils import (
    get_slurm_job_name,
    get_slurm_log_file,
    get_slurm_sim_experiment_dir,
    get_slurm_sim_input_file_path,
    get_slurm_sim_results_file_path,
    get_slurm_singularity_def_file,
    get_slurm_submit_file,
)
from compose_api.simulation.models import PBWhiteList, Simulation

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SimulationService(ABC):
    @abstractmethod
    async def submit_simulation_job(
        self,
        white_list: PBWhiteList,
        simulation: Simulation,
        database_service: DatabaseService,
        correlation_id: str,
    ) -> int:
        pass

    @abstractmethod
    async def get_slurm_job_status(self, slurmjobid: int) -> SlurmJob | None:
        pass

    @abstractmethod
    async def get_slurm_job_result_path(self, slurmjobid: int) -> Path | None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class SimulationServiceHpc(SimulationService):
    _latest_commit_hash: str | None = None

    @staticmethod
    def _get_services() -> tuple[SlurmService, SSHService, Settings]:
        settings = get_settings()
        ssh_service = get_ssh_service(settings)
        return SlurmService(ssh_service=ssh_service), ssh_service, settings

    @override
    async def submit_simulation_job(
        self,
        white_list: PBWhiteList,
        simulation: Simulation,
        database_service: DatabaseService,
        correlation_id: str,
    ) -> int:
        if database_service is None:
            raise RuntimeError("DatabaseService is not available. Cannot submit Simulation job.")
        if simulation.sim_request.omex_archive is None:
            raise RuntimeError("Simulation.sim_request.omex_archive is not available. Cannot submit Simulation job.")

        slurm_service, ssh_service, settings = self._get_services()
        slurm_job_name = get_slurm_job_name(correlation_id=correlation_id)
        slurm_log_file = get_slurm_log_file(slurm_job_name=slurm_job_name)
        slurm_submit_file = get_slurm_submit_file(slurm_job_name=slurm_job_name)
        slurm_singularity_file = get_slurm_singularity_def_file(slurm_job_name=slurm_job_name)
        slurm_input_file = get_slurm_sim_input_file_path(slurm_job_name=slurm_job_name)
        experiment_path = get_slurm_sim_experiment_dir(slurm_job_name=slurm_job_name)

        # build the submit script
        with tempfile.TemporaryDirectory() as tmpdir:
            local_singularity_file = tmpdir + "/singularity.def"
            processed_omex = Path(tmpdir + f"/{os.path.basename(simulation.sim_request.omex_archive.name)}")
            execute_bsander(
                ProgramArguments(
                    input_file_path=str(simulation.sim_request.omex_archive),
                    output_dir=tmpdir,
                    containerization_type=ContainerizationTypes.SINGLE,
                    containerization_engine=ContainerizationEngine.APPTAINER,
                    whitelist_entries=white_list.white_list,
                )
            )
            local_submit_file = Path(tmpdir) / f"{slurm_job_name}.sbatch"
            # --compat forces isolation similar to docker, https://docs.sylabs.io/guides/latest/user-guide/cli/singularity_exec.html
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

                    set -e

                    # singularity build sim-{slurm_job_name}.sif {slurm_singularity_file}
                    echo "Simulation {slurm_job_name} running."
                    singularity exec \
                        --compat \
                        --bind {experiment_path}:/experiment \
                        {settings.hpc_image_base_path}/test.sif \
                         python3 /runtime/main.py /experiment/{slurm_job_name}.omex
                    pushd {experiment_path}/output/
                    zip -r {experiment_path}/results.zip ./*
                    popd
                    echo "Simulation run completed. data saved to {experiment_path!s}."
                    """)
                f.write(script_content)

            await ssh_service.run_command(f"mkdir {experiment_path}")
            # submit the build script to slurm
            slurm_jobid = await slurm_service.submit_job(
                local_sbatch_file=local_submit_file,
                remote_sbatch_file=slurm_submit_file,
                local_input_file=processed_omex,
                remote_input_file=slurm_input_file,
                local_singularity_file=Path(local_singularity_file),
                remote_singularity_file=slurm_singularity_file,
            )
            return slurm_jobid

    async def get_slurm_job(self, slurmjobid: int) -> SlurmJob | None:
        slurm_service, _, _ = self._get_services()
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
    async def get_slurm_job_status(self, slurmjobid: int) -> SlurmJob | None:
        result = await self.get_slurm_job(slurmjobid)
        return result

    @override
    async def get_slurm_job_result_path(self, slurmjobid: int) -> Path:
        slurm_job = await self.get_slurm_job(slurmjobid)
        if slurm_job is None:
            raise ValueError(f"No job found with ID {slurmjobid}")
        if not slurm_job.is_done():
            raise RuntimeError(f"Job {slurmjobid} is not yet done.")
        if slurm_job.job_state != "COMPLETED":
            raise RuntimeError(f"Job `{slurmjobid}` has state `{slurm_job.job_state}`, not `COMPLETED`")
        correlation_id = slurm_job.name
        return get_slurm_sim_results_file_path(correlation_id)

    @override
    async def close(self) -> None:
        pass
