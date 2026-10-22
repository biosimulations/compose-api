"""The drift alarm between the two SLURM backends.

Every other SLURM test asserts what our code does with the scheduler's output. This one
asserts the shape of the output itself, because that is where the throwaway container and
the production cluster can silently diverge: a different SLURM version changes a field
count or a state spelling, our parsers keep running, and the meaning quietly changes.

It runs on whichever backends are selected, so running with both
(``--slurm-backend container --slurm-backend cluster``) compares them.
"""

import asyncio
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from compose_api.common.hpc.models import SlurmJob
from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.common.ssh.ssh_service import SSHService
from compose_api.simulation.hpc_utils import _namespace_path
from compose_api.simulation.models import JobStatus
from tests.fixtures.slurm_fixtures_backend import SlurmBackend

SQUEUE_FIELDS = 5  # %i|%j|%a|%u|%T
SACCT_FIELDS = 9  # jobid,jobname,account,user,state,start,end,elapsed,exitcode
# `--parsable` terminates every row with the delimiter too, so a split yields one
# trailing empty field. `--parsable2` would not. The parser indexes positionally and
# ignores the extra, but the count is still worth pinning.


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_sbatch_parsable_returns_a_bare_integer(
    slurm_backend: SlurmBackend, slurm_service: SlurmService, slurm_template_hello_1s: str
) -> None:
    """`_execute_sbatch_command` does `int(stdout)` with no parsing, so this must hold."""
    remote_dir = _namespace_path() / "htclogs"
    with tempfile.TemporaryDirectory() as tmpdir:
        local = Path(tmpdir) / f"conformance_{uuid.uuid4().hex}.sbatch"
        local.write_text(slurm_template_hello_1s)
        job_id = await slurm_service._submit_canary_job(
            local_sbatch_file=local, remote_sbatch_file=remote_dir / local.name
        )
    assert isinstance(job_id, int)
    assert job_id > 0


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_squeue_emits_the_fields_the_parser_indexes(
    slurm_backend: SlurmBackend, ssh_service: SSHService, slurm_service: SlurmService, slurm_template_hello_10s: str
) -> None:
    remote_dir = _namespace_path() / "htclogs"
    with tempfile.TemporaryDirectory() as tmpdir:
        local = Path(tmpdir) / f"conformance_{uuid.uuid4().hex}.sbatch"
        local.write_text(slurm_template_hello_10s)
        job_id = await slurm_service._submit_canary_job(
            local_sbatch_file=local, remote_sbatch_file=remote_dir / local.name
        )

    command = f'squeue -u $USER --noheader --format="{SlurmJob.get_squeue_format_string()}" -j {job_id}'
    return_code, stdout, _stderr = await ssh_service.run_command(command=command)
    assert return_code == 0
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, f"squeue reported nothing for job {job_id}"

    for line in lines:
        fields = line.strip().split("|")
        assert len(fields) == SQUEUE_FIELDS, f"squeue emitted {len(fields)} fields, parser indexes {SQUEUE_FIELDS}"
        assert fields[0].isdigit(), f"job id {fields[0]!r} is not a bare integer"
        # The monitor does JobStatus(state.lower()); an unmapped spelling becomes UNKNOWN.
        assert fields[4].lower() in set(JobStatus), f"squeue state {fields[4]!r} has no JobStatus member"


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_sacct_emits_the_fields_the_parser_indexes(
    slurm_backend: SlurmBackend, ssh_service: SSHService, slurm_service: SlurmService, slurm_template_hello_1s: str
) -> None:
    """sacct needs slurmdbd; a backend without accounting fails here rather than silently."""
    remote_dir = _namespace_path() / "htclogs"
    with tempfile.TemporaryDirectory() as tmpdir:
        local = Path(tmpdir) / f"conformance_{uuid.uuid4().hex}.sbatch"
        local.write_text(slurm_template_hello_1s)
        job_id = await slurm_service._submit_canary_job(
            local_sbatch_file=local, remote_sbatch_file=remote_dir / local.name
        )

    command = (
        f'sacct -u $USER --parsable --allocations --delimiter="|" --noheader '
        f'--format="{SlurmJob.get_sacct_format_string()}" -j {job_id}'
    )
    return_code, stdout, _stderr = await ssh_service.run_command(command=command)
    assert return_code == 0
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, f"sacct reported nothing for job {job_id}; is accounting configured?"

    for line in lines:
        fields = line.strip().split("|")
        assert len(fields) >= SACCT_FIELDS, f"sacct emitted {len(fields)} fields, parser indexes {SACCT_FIELDS}"
        assert all(extra == "" for extra in fields[SACCT_FIELDS:]), (
            f"sacct emitted unexpected data past field {SACCT_FIELDS}: {fields[SACCT_FIELDS:]!r}"
        )
        assert fields[0].split(".")[0].isdigit(), f"job id {fields[0]!r} does not start with an integer"

    # The parser must survive its own backend's output.
    parsed = await slurm_service.get_job_status_sacct(job_ids=[job_id])
    assert [job.job_id for job in parsed] == [job_id]


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_a_job_is_found_by_its_name_while_queued_and_after_it_finished(
    slurm_backend: SlurmBackend, ssh_service: SSHService, slurm_service: SlurmService, slurm_template_hello_1s: str
) -> None:
    """The submission worker adopts a job an earlier attempt submitted by looking it up by name
    (``SlurmService.find_job_by_name``): ``squeue --name`` while it is queued or running, ``sacct --name`` after."""
    name = f"conformance-{uuid.uuid4().hex[:12]}"
    remote_dir = _namespace_path() / "htclogs"
    with tempfile.TemporaryDirectory() as tmpdir:
        local = Path(tmpdir) / f"{name}.sbatch"
        local.write_text(slurm_template_hello_1s.replace("--job-name=my_test_job", f"--job-name={name}"))
        job_id = await slurm_service._submit_canary_job(
            local_sbatch_file=local, remote_sbatch_file=remote_dir / local.name
        )
    assert await slurm_service.find_job_by_name(name) == job_id
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        _rc, queued, _err = await ssh_service.run_command(f"squeue --noheader --name={name} --format=%i")
        if not queued.strip():
            break
        await asyncio.sleep(2)
    assert await slurm_service.find_job_by_name(name) == job_id, "a finished job is found through sacct"
    assert await slurm_service.find_job_by_name(f"no-such-job-{uuid.uuid4().hex[:8]}") is None
