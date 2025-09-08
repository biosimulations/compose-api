import logging
from pathlib import Path

import asyncssh
from asyncssh import SSHCompletedProcess

from compose_api.config import Settings, get_settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SSHService:
    hostname: str
    username: str
    key_path: Path
    known_hosts: str | None

    def __init__(self, hostname: str, username: str, key_path: Path, known_hosts: Path | None = None) -> None:
        self.hostname = hostname
        self.username = username
        self.key_path = key_path
        self.known_hosts = str(known_hosts) if known_hosts else None

    async def run_command(self, command: str) -> tuple[int, str, str]:
        async with asyncssh.connect(
            host=self.hostname, username=self.username, client_keys=[self.key_path], known_hosts=self.known_hosts
        ) as conn:
            try:
                logger.info(f"Running ssh command: {command}")
                result: SSHCompletedProcess = await conn.run(command, check=True)
                if not isinstance(result.stdout, str):
                    raise TypeError(f"Expected result.stdout to be str, got {type(result.stdout)}")
                if not isinstance(result.stderr, str):
                    raise TypeError(f"Expected result.stderr to be str, got {type(result.stderr)}")
                if not isinstance(result.returncode, int):
                    raise TypeError(f"Expected result.returncode to be int, got {type(result.returncode)}")
                logger.info(
                    msg=f"command {command} retcode {result.returncode} "
                    f"stdout={result.stdout[:100]} stderr={result.stderr[:100]}"
                )
                return result.returncode, result.stdout, result.stderr
            except asyncssh.ProcessError as exc:
                logger.exception(msg=f"failed to send command `{command}`, stderr:\n\t{exc.stderr!s}", exc_info=exc)
                raise RuntimeError(f"failed to send command `{command}`, stderr:\n\t{exc.stderr!s})") from exc
            except (OSError, asyncssh.Error) as exc:
                logger.exception(msg=f"failed to send command `{command}`, stderr:\n\t{exc!s}", exc_info=exc)
                raise RuntimeError(f"failed to send command `{command}`, stderr:\n\t{exc!s}") from exc

    async def scp_upload(self, local_file: Path, remote_path: Path) -> None:
        async with asyncssh.connect(
            host=self.hostname, username=self.username, client_keys=[self.key_path], known_hosts=self.known_hosts
        ) as conn:
            try:
                await asyncssh.scp(srcpaths=local_file, dstpath=(conn, remote_path))
                logger.info(msg=f"sent file {local_file} to {remote_path}")
            except asyncssh.Error as exc:
                logger.exception(msg=f"failed to send file {local_file} to {remote_path}", exc_info=exc)
                raise RuntimeError(f"failed to send file {local_file} to {remote_path}, error {exc!s}") from exc

    async def scp_download(self, local_file: Path, remote_path: Path) -> None:
        async with asyncssh.connect(
            host=self.hostname, username=self.username, client_keys=[self.key_path], known_hosts=self.known_hosts
        ) as conn:
            try:
                await asyncssh.scp(srcpaths=(conn, remote_path), dstpath=local_file)
                logger.info(msg=f"retrieved remote file {remote_path} to {local_file}")
            except asyncssh.Error as exc:
                logger.exception(msg=f"failed to retrieve remote file {remote_path} to {local_file}", exc_info=exc)
                raise RuntimeError(
                    f"failed to retrieve remote file {remote_path} to {local_file}, error {exc!s}"
                ) from exc

    async def close(self) -> None:
        pass  # nothing to do here because we don't yet keep the connection around.


def get_custom_ssh_service(settings: Settings) -> SSHService:
    return SSHService(
        hostname=settings.slurm_submit_host,
        username=settings.slurm_submit_user,
        key_path=Path(settings.slurm_submit_key_path),
        known_hosts=Path(settings.slurm_submit_known_hosts) if settings.slurm_submit_known_hosts else None,
    )


def get_ssh_service() -> SSHService:
    return get_custom_ssh_service(get_settings())
