"""The sbatch script under a real SLURM time limit. At the limit SLURM sends SIGTERM to every process of the job, then
SIGKILL after KillWait. A simulator deaf to SIGTERM (runs 12536-12538, hung on one node) must not keep the job from
recording its end and announcing its SLURM log, and must not outlive the job on the node."""

import asyncio
import json
import shlex
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.simulation.hpc_utils import get_slurm_sim_experiment_dir, get_slurm_sim_log_file
from compose_api.simulation.job_script import SimulationJob, simulation_job_script
from tests.fixtures.slurm_fixtures_backend import SlurmBackend

# Stands in for singularity: hung, and deaf to SIGTERM, so only SLURM's SIGKILL ends it. It stays a bash process, so
# its command line keeps its own path (under the experiment directory) and it can be found afterwards; an exec'd sleep
# may be a coreutils shebang script, which loses any name given to it.
DEAF_SINGULARITY = "#!/bin/bash\ntrap '' TERM\nwhile :; do sleep 1; done\n"


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_a_time_limit_records_the_job_end_and_its_log_while_the_simulator_ignores_sigterm(
    slurm_backend: SlurmBackend, slurm_service: SlurmService
) -> None:
    ssh = slurm_backend.ssh_service
    experiment_id = f"time-limit-{uuid.uuid4().hex[:8]}"
    experiment = get_slurm_sim_experiment_dir(experiment_id)
    bin_dir = experiment / "bin"
    script = simulation_job_script(
        SimulationJob(
            job_name=experiment_id,
            experiment_id=experiment_id,
            simulation_id=1,
            correlation_id=f"simulation-{experiment_id}",
            experiment_dir=str(experiment),
            container="image.sif",
            file_suffix="omex",
            output_dir="/experiment/output",
            end_time=1.0,
            log_file=str(get_slurm_sim_log_file(experiment_id)),
            is_batch=True,
            partition=slurm_backend.partition,
            qos=slurm_backend.qos,
        )
    )
    await ssh.run_command(f"mkdir -p {shlex.quote(str(bin_dir))}")
    job_ids: list[int] = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fake, sbatch = Path(tmp) / "singularity", Path(tmp) / "job.sbatch"
            fake.write_text(DEAF_SINGULARITY)
            sbatch.write_text(script)
            await ssh.scp_upload(local_file=fake, remote_path=bin_dir / "singularity")
            await ssh.scp_upload(local_file=sbatch, remote_path=experiment / "job.sbatch")
        await ssh.run_command(f"chmod +x {shlex.quote(str(bin_dir / 'singularity'))}")
        # The shortest time limit SLURM takes (one minute) and a small allocation override the script's own; the fake
        # singularity comes first on the PATH the job inherits.
        code, out, err = await ssh.run_command(
            f"cd {shlex.quote(str(experiment))} && PATH={shlex.quote(str(bin_dir))}:$PATH "
            "sbatch --parsable --time=1 --mem=100M --cpus-per-task=1 job.sbatch"
        )
        assert code == 0, err
        job_id = int(out.strip().split(";")[0])
        job_ids.append(job_id)
        assert (await _ended(slurm_service, job_id)).startswith("TIMEOUT")

        # Nothing of the job is left on its node: a second job there looks for the simulator by its path (exit 3 if
        # found, 4 if it cannot look).
        _, node, _ = await ssh.run_command(f"sacct -j {job_id} -X -n -P -o NodeList")
        fake_path = shlex.quote(str(bin_dir / "singularity"))
        look = f"command -v pgrep >/dev/null || exit 4; pgrep -f {fake_path} && exit 3; exit 0"
        code, out, err = await ssh.run_command(
            f"sbatch --parsable -w {shlex.quote(node.strip())} --time=1 --mem=10M --cpus-per-task=1 "
            f"--output={shlex.quote(str(experiment / 'probe.out'))} --wrap {shlex.quote(look)}"
        )
        assert code == 0, err
        probe = int(out.strip().split(";")[0])
        job_ids.append(probe)
        assert (await _ended(slurm_service, probe)).startswith("COMPLETED"), "the simulator outlived its job"

        _, text, _ = await ssh.run_command(f"cat {shlex.quote(str(experiment / 'events' / 'job.jsonl'))}")
        events = [json.loads(line) for line in text.splitlines() if line.strip()]
        names = [e["event"] for e in events]
        assert names[-2:] == ["job.end", "span.end"], names
        assert events[-2]["payload"]["exit_code"] == 143
        assert {"uri": "job.out", "kind": "log", "name": "SLURM log"} in [
            e["payload"] for e in events if e["event"] == "artifact.written"
        ]
    finally:
        if job_ids:
            await ssh.run_command(f"scancel {' '.join(map(str, job_ids))}")
        await ssh.run_command(f"rm -rf {shlex.quote(str(experiment))}")


async def _ended(slurm_service: SlurmService, job_id: int) -> str:
    """The job's final state, once it has one."""
    deadline = time.monotonic() + 300  # a time limit, SLURM's sweep for it, then KillWait
    while True:
        jobs = await slurm_service.get_job_status_sacct(job_ids=[job_id])
        if jobs and jobs[0].job_state.split()[0] in {"TIMEOUT", "CANCELLED", "FAILED", "COMPLETED", "NODE_FAIL"}:
            return jobs[0].job_state
        assert time.monotonic() < deadline, f"job {job_id} never ended: {jobs}"
        await asyncio.sleep(5)
