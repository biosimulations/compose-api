import logging
import shlex
from pathlib import Path

from compose_api.common.hpc.models import SlurmJob
from compose_api.common.ssh.ssh_service import SSHService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SlurmService:
    ssh_service: SSHService

    def __init__(self, ssh_service: SSHService):
        self.ssh_service = ssh_service

    async def get_job_status_squeue(self, job_ids: list[int] | None = None) -> list[SlurmJob]:
        command = f'squeue -u $USER --noheader --format="{SlurmJob.get_squeue_format_string()}"'
        if job_ids is not None:
            job_ids_str = ",".join(map(str, job_ids)) if len(job_ids) > 1 else str(job_ids[0])
            command = command + f" -j {job_ids_str}"
        return_code, stdout, stderr = await self.ssh_service.run_command(command=command)
        if return_code != 0:
            raise Exception(
                f"failed to get job status with command {command} return code {return_code} stderr {stderr[:100]}"
            )
        slurm_jobs: list[SlurmJob] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            slurm_jobs.append(SlurmJob.from_squeue_formatted_output(line.strip()))
        return slurm_jobs

    async def get_job_status_sacct(self, job_ids: list[int] | None = None) -> list[SlurmJob]:
        command = f'sacct -u $USER --parsable --allocations --delimiter="|" --noheader --format="{SlurmJob.get_sacct_format_string()}"'  # noqa: E501
        if job_ids is not None:
            job_ids_str = ",".join(map(str, job_ids)) if len(job_ids) > 1 else str(job_ids[0])
            command = command + f" -j {job_ids_str}"
        return_code, stdout, stderr = await self.ssh_service.run_command(command=command)
        if return_code != 0:
            raise Exception(
                f"failed to get job status with command {command} return code {return_code} stderr {stderr[:100]}"
            )
        slurm_jobs: list[SlurmJob] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            # skip lines which are .batch and ?? jobs
            if line.split("|")[0].endswith(".batch"):
                continue
            if line.split("|")[0].endswith(".extern"):
                continue
            slurm_jobs.append(SlurmJob.from_sacct_formatted_output(line.strip()))
        return slurm_jobs

    async def _submit_canary_job(self, local_sbatch_file: Path, remote_sbatch_file: Path) -> int:
        """
        Focused on submitting a canary job that simply print's hello world.
        Used to ensure SLURM submission is functioning correctly.
        """
        await self.ssh_service.scp_upload(local_file=local_sbatch_file, remote_path=remote_sbatch_file)
        return await self._execute_sbatch_command(sbatch_file=remote_sbatch_file)

    async def submit_job(
        self,
        local_sbatch_file: Path,
        remote_sbatch_file: Path,
        local_input_file: Path | None,
        remote_input_file: Path | None,
    ) -> int:
        """Upload the script (and the input, unless it is already in place on the cluster) and sbatch it."""
        await self.ssh_service.scp_upload(local_file=local_sbatch_file, remote_path=remote_sbatch_file)
        if local_input_file is not None and remote_input_file is not None:
            await self.ssh_service.scp_upload(local_file=local_input_file, remote_path=remote_input_file)
        return await self._execute_sbatch_command(sbatch_file=remote_sbatch_file)

    async def find_job_by_name(self, job_name: str) -> int | None:
        """The newest job named ``job_name``, queued or running (squeue) or already finished (sacct, last 30 days); None
        when there is none. A run's job is named by its experiment id, so this finds a job an earlier attempt submitted
        before it could record it (docs/plan-durable-submission.md, Q2)."""
        name = shlex.quote(job_name)
        for command in (
            f"squeue --noheader --name={name} --format=%i",
            f"sacct --noheader --allocations --parsable2 --name={name} --format=JobID --starttime=now-30days",
        ):
            return_code, stdout, stderr = await self.ssh_service.run_command(command=command)
            if return_code != 0:
                raise RuntimeError(f"{command.split()[0]} could not look up job {job_name}: {stderr[:200]}")
            ids = [int(token) for token in stdout.split() if token.strip().isdigit()]
            if ids:
                return max(ids)
        return None

    async def cancel_job(self, job_id: int) -> None:
        """``scancel`` the job. SLURM accepts a job that has already ended and does nothing, so this is idempotent."""
        command = f"scancel {int(job_id)}"
        return_code, _stdout, stderr = await self.ssh_service.run_command(command=command)
        if return_code != 0:
            raise RuntimeError(f"scancel could not cancel job {job_id}: {stderr[:200]}")

    async def submit_build_job(
        self,
        local_sbatch_file: Path,
        remote_sbatch_file: Path,
        local_singularity_file: Path,
        remote_singularity_file: Path,
    ) -> int:
        await self.ssh_service.scp_upload(local_file=local_sbatch_file, remote_path=remote_sbatch_file)
        await self.ssh_service.scp_upload(local_file=local_singularity_file, remote_path=remote_singularity_file)
        return await self._execute_sbatch_command(sbatch_file=remote_sbatch_file)

    async def _execute_sbatch_command(self, sbatch_file: Path) -> int:
        command = f"sbatch --parsable {sbatch_file}"
        return_code, stdout, stderr = await self.ssh_service.run_command(command=command)
        if return_code != 0:
            raise Exception(
                f"failed to get job status with command {command} return code {return_code} stderr {stderr[:100]}"
            )
        return int(stdout)
