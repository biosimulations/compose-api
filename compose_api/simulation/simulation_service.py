import logging
import random
import string
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from textwrap import dedent

from typing_extensions import override

from compose_api.common.hpc.models import SlurmJob
from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.common.ssh.ssh_service import SSHService, get_ssh_service
from compose_api.config import Settings, get_settings
from compose_api.dependencies import get_required_database_service
from compose_api.simulation.hpc_utils import (
    get_correlation_id,
    get_slurm_job_name,
    get_slurm_log_file,
    get_slurm_sim_experiment_dir,
    get_slurm_sim_input_file_path,
    get_slurm_sim_results_file_path,
    get_slurm_singularity_container_file,
    get_slurm_singularity_def_file,
    get_slurm_submit_file,
)
from compose_api.simulation.models import HpcRun, JobType, Simulation, SimulatorVersion

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SimulationService(ABC):
    @abstractmethod
    async def submit_simulation_job(
        self,
        simulation: Simulation,
        experiment_id: str,
    ) -> int:
        pass

    @abstractmethod
    async def build_container(self, simulator_version: SimulatorVersion, random_str: str) -> HpcRun:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class SimulationServiceHpc(SimulationService):
    _latest_commit_hash: str | None = None

    @staticmethod
    def _get_services() -> tuple[SlurmService, SSHService, Settings]:
        settings = get_settings()
        ssh_service = get_ssh_service()
        return SlurmService(ssh_service=ssh_service), ssh_service, settings

    @override
    async def submit_simulation_job(
        self,
        simulation: Simulation,
        experiment_id: str,
    ) -> int:
        if simulation.sim_request.omex_archive is None:
            raise RuntimeError("Simulation.sim_request.omex_archive is not available. Cannot submit Simulation job.")
        slurm_service, ssh_service, settings = self._get_services()
        slurm_job_name = get_slurm_job_name(experiment_id=experiment_id)
        singularity_container_path = get_slurm_singularity_container_file(
            singularity_hash=simulation.simulator_version.singularity_def_hash
        )
        experiment_path = get_slurm_sim_experiment_dir(experiment_id=slurm_job_name)

        # build the submit script
        with tempfile.TemporaryDirectory() as tmpdir:
            local_singularity_file = tmpdir + "/singularity.def"
            with open(local_singularity_file, "w") as f:
                f.write(simulation.simulator_version.singularity_def.representation)

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
                    #SBATCH --output={get_slurm_log_file(slurm_job_name=slurm_job_name)}

                    set -e

                    echo "Simulation {slurm_job_name} running."
                    singularity exec \
                        --compat \
                        --bind {experiment_path}:/experiment \
                        {singularity_container_path} \
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
                remote_sbatch_file=get_slurm_submit_file(slurm_job_name=slurm_job_name),
                local_input_file=simulation.sim_request.omex_archive,
                remote_input_file=get_slurm_sim_input_file_path(experiment_id=slurm_job_name),
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
    async def build_container(self, simulator_version: SimulatorVersion, random_str: str) -> HpcRun:
        slurm_service, ssh_service, settings = self._get_services()

        with tempfile.TemporaryDirectory() as tmpdir:
            local_singularity_file = Path(tmpdir + "/singularity.def")
            rand_string = "".join(random.choices(string.hexdigits, k=5))  # noqa: S311
            slurm_job_name = f"singularity_build_{simulator_version.singularity_def_hash[:5]}_{rand_string}"
            singularity_container_path = get_slurm_singularity_container_file(
                singularity_hash=simulator_version.singularity_def_hash
            )

            singularity_def_file = get_slurm_singularity_def_file(
                singularity_hash=simulator_version.singularity_def_hash
            )
            def_file_name = singularity_def_file.name.split("/")[-1]
            container_file_name = singularity_container_path.name.split("/")[-1]

            with open(local_singularity_file, "w") as f:
                f.write(simulator_version.singularity_def.representation)

            local_submit_file = Path(tmpdir) / f"{slurm_job_name}.sbatch"
            with open(local_submit_file, "w") as f:
                script_content = dedent(f"""\
                    #!/bin/bash
                    #SBATCH --job-name={slurm_job_name}
                    #SBATCH --time=30:00
                    #SBATCH --cpus-per-task 1
                    #SBATCH --mem=4GB
                    #SBATCH --nodelist={settings.slurm_build_node}
                    #SBATCH --partition=general
                    #SBATCH --qos=general
                    #SBATCH --output={get_slurm_log_file(slurm_job_name=slurm_job_name)}

                    set -e
                    echo "Starting build for container {singularity_container_path}"
                    pushd /tmp
                    mv {singularity_def_file} /tmp/{def_file_name}
                    singularity build --fakeroot {container_file_name} {def_file_name}
                    mv {container_file_name} {singularity_container_path}
                    mv {def_file_name} {singularity_def_file} # Cleanup
                    popd
                    echo "Finished building container."
                    """)
                f.write(script_content)

            # submit the build script to slurm
            slurm_jobid = await slurm_service.submit_build_job(
                local_sbatch_file=local_submit_file,
                remote_sbatch_file=get_slurm_submit_file(slurm_job_name=slurm_job_name),
                local_singularity_file=local_singularity_file,
                remote_singularity_file=singularity_def_file,
            )

            hpc_run = (
                await get_required_database_service()
                .get_hpc_db()
                .insert_hpcrun(
                    slurmjobid=slurm_jobid,
                    job_type=JobType.BUILD_CONTAINER,
                    ref_id=simulator_version.database_id,
                    correlation_id=get_correlation_id(random_string=random_str, job_type=JobType.BUILD_CONTAINER),
                )
            )

            return hpc_run

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
