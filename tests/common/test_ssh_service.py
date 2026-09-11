import tempfile
import uuid
from pathlib import Path

import pytest

from compose_api.common.ssh.ssh_service import SSHService
from tests.fixtures.slurm_fixtures_backend import SlurmBackend


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_ssh_command(slurm_backend: SlurmBackend, ssh_service: SSHService) -> None:
    return_code, _stdout, _stderr = await ssh_service.run_command("hostname")
    assert return_code == 0
    # assert stdout.strip("\n") == ssh_service.hostname  # hostname may be different if behind a proxy server


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_scp_upload_download(slurm_backend: SlurmBackend, ssh_service: SSHService) -> None:
    # create local temp text file with content "hello world"
    with tempfile.NamedTemporaryFile(mode="w+") as f:
        f.write("hello world")
        f.flush()

        # Under the backend's own base path rather than a relative path resolved against
        # the login home, and created here: scp does not make parent directories, and on
        # the container nothing has made one for us.
        remote_dir = slurm_backend.remote_base / f"test_servers_scp_{uuid.uuid4().hex}"
        remote_path = remote_dir / "remote_temp.txt"
        assert (await ssh_service.run_command(f"mkdir -p {remote_dir}"))[0] == 0

        with tempfile.NamedTemporaryFile(mode="w+") as f2:
            await ssh_service.scp_upload(local_file=Path(f.name), remote_path=remote_path)
            await ssh_service.scp_download(remote_path=remote_path, local_file=Path(f2.name))
            f2.flush()
            f2.seek(0)
            assert f2.read() == "hello world"

            return_code, _stdout, _stderr = await ssh_service.run_command(f"rm -r {remote_dir}")
            assert return_code == 0
