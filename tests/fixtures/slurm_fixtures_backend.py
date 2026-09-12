"""Backend selection for the SSH/SLURM tests.

One test body runs against either backend:

* ``container`` -- a throwaway SLURM cluster from ``tests/fixtures/slurm_cluster``,
  requiring only Docker. This is what CI uses.
* ``cluster``   -- the real submit host named in settings, requiring a key and VPN.
  Opt in with ``--slurm-backend cluster``.

Selection is per-test parameterisation rather than a fork in the test body, so the two
backends cannot drift: there is exactly one body. Differences between them are *data* on
:class:`SlurmBackend`, never a branch on ``kind``.

The switch itself is a settings override, not an injected object, because three separate
consumers reach for SSH independently (``SimulationServiceHpc``, ``DataService`` and the
``SlurmService`` inside ``JobMonitor``). Injecting into two and forgetting the third would
leave the third talking to the real cluster. Overriding settings reaches all of them,
including ones added later.
"""

import asyncio
import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import asyncssh
import pytest

from compose_api.common.ssh.ssh_service import SSHService, get_ssh_service
from compose_api.config import Settings, get_settings, override_settings
from compose_api.simulation.hpc_utils import _namespace_path

COMPOSE_DIR = Path(__file__).parent / "slurm_cluster"
CONTAINER_USER = "root"
CONTAINER_PARTITION = "cpu"
# slurmdbd creates a `normal` QOS; naming it keeps the sbatch templates identical to
# production, which always emits a --qos directive.
CONTAINER_QOS = "normal"
# The first worker replica. `build_container` pins the build to one node by name.
CONTAINER_BUILD_NODE = "c1"


@dataclass(frozen=True)
class SlurmBackend:
    """What a test needs to know about the scheduler it is talking to.

    Read these instead of reaching into settings, so that adding a new difference between
    the backends means adding a field here -- visible in review -- rather than a branch.
    """

    kind: Literal["container", "cluster"]
    partition: str
    qos: str
    remote_base: Path
    can_build_singularity: bool

    @property
    def ssh_service(self) -> SSHService:
        """A descriptor built from the settings currently in force."""
        return get_ssh_service()


@dataclass(frozen=True)
class _ContainerCluster:
    """Connection details for the throwaway cluster, typed so callers need no casts."""

    port: int
    key_path: Path
    env: dict[str, str]


def _compose(*args: str, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["docker", "compose", *args],  # noqa: S607
        cwd=COMPOSE_DIR,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def docker_available() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "info"],  # noqa: S607
                capture_output=True,
                check=False,
                timeout=15,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def cluster_credentials_present() -> bool:
    settings = get_settings()
    return bool(settings.slurm_submit_key_path) and Path(settings.slurm_submit_key_path).exists()


async def _ssh_probe(port: int, key_path: Path) -> None:
    async with asyncssh.connect(
        host="127.0.0.1",
        port=port,
        username=CONTAINER_USER,
        client_keys=[str(key_path)],
        known_hosts=None,
    ) as conn:
        await conn.run("true", check=True)


def _wait_for_ssh(port: int, key_path: Path, env: dict[str, str], timeout_seconds: float = 90.0) -> None:
    """Block until the cluster actually accepts an SSH session.

    ``docker compose up --wait`` only waits for the healthchecks, and slurmctld's is
    ``scontrol ping``, which says nothing about sshd: the entrypoint backgrounds sshd and
    goes on to start the controller, so the container can be healthy while SSH is not yet
    usable, or while sshd has already died. Probing the real thing turns that race into a
    wait, and a genuine misconfiguration into one clear error carrying the container's own
    logs, instead of every SSH test failing separately with ``ConnectionLost``.
    """
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            asyncio.run(_ssh_probe(port, key_path))
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    ps = _compose("ps", env=env, check=False).stdout
    logs = _compose("logs", "--no-color", "--tail", "60", "slurmctld", env=env, check=False).stdout
    raise RuntimeError(
        f"the SLURM container never accepted SSH on 127.0.0.1:{port} "
        f"within {timeout_seconds:.0f}s; last error was {last_error!r}\n\n{ps}\n\n{logs}"
    )


@pytest.fixture(scope="session")
def _container_cluster(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_ContainerCluster]:
    """Bring up the throwaway cluster once per session and yield its connection details."""
    workdir = tmp_path_factory.mktemp("slurm-cluster")
    key_path = workdir / "id_ed25519"
    subprocess.run(  # noqa: S603
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-f", str(key_path)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    authorized_keys = workdir / "authorized_keys"
    authorized_keys.write_text(key_path.with_suffix(".pub").read_text())
    authorized_keys.chmod(0o644)

    # A unique project name per session keeps concurrent runs from colliding, and the
    # worker entrypoint needs the same value to derive its node name.
    project = f"composeapi-slurm-{uuid.uuid4().hex[:8]}"
    env = {
        **os.environ,
        "SSH_AUTHORIZED_KEYS": str(authorized_keys),
        "COMPOSE_PROJECT_NAME": project,
    }
    _compose("down", "-v", "--remove-orphans", env=env, check=False)
    _compose("up", "-d", "--wait", env=env)
    try:
        # `docker compose port` can print one line per address family; they carry the
        # same published port, so take the first and parse it alone.
        published = _compose("port", "slurmctld", "22", env=env).stdout.strip().splitlines()[0]
        port = int(published.rsplit(":", 1)[1])
        _wait_for_ssh(port=port, key_path=key_path, env=env)
        yield _ContainerCluster(port=port, key_path=key_path, env=env)
    finally:
        _compose("down", "-v", "--remove-orphans", env=env, check=False)


def _provision_remote_tree(env: dict[str, str]) -> None:
    """Create the directory tree the production code expects to already exist.

    ``simulation_service`` makes a per-experiment directory but never its parents, so on
    the real cluster ``sims/``, ``htclogs/``, ``slurm_sbatch/`` and ``images/`` were made
    once by an administrator. Match that here rather than teaching the production code to
    ``mkdir -p``, so the container exercises the same code path the cluster does.

    Run through ``docker compose exec`` rather than SSH: this fixture is synchronous, and
    ``/data`` is a shared volume, so the workers see it too. The paths come from
    ``_namespace_path()`` so they cannot drift from what the production code writes to.
    """
    base = _namespace_path()
    dirs = [str(base / name) for name in ("sims", "htclogs", "slurm_sbatch", "images")]
    _compose("exec", "-T", "slurmctld", "mkdir", "-p", *dirs, env=env)


@pytest.fixture(scope="session")
def slurm_backend(request: pytest.FixtureRequest) -> Iterator[SlurmBackend]:
    """Yield the selected backend, with settings pointed at it for the whole session."""
    kind: str = request.param
    if kind == "cluster":
        if not cluster_credentials_present():
            pytest.skip("slurm_submit_key_path is unset or missing; cannot reach the real cluster")
        settings: Settings = get_settings()
        yield SlurmBackend(
            kind="cluster",
            partition=settings.slurm_partition,
            qos=settings.slurm_qos,
            remote_base=Path(settings.simulation_store_base_path),
            can_build_singularity=True,
        )
        return

    details: _ContainerCluster = request.getfixturevalue("_container_cluster")
    remote_base = Path("/data/compose-api")
    with override_settings(
        slurm_submit_host="127.0.0.1",
        slurm_submit_port=details.port,
        slurm_submit_user=CONTAINER_USER,
        slurm_submit_key_path=str(details.key_path),
        slurm_submit_known_hosts=None,
        slurm_partition=CONTAINER_PARTITION,
        slurm_qos=CONTAINER_QOS,
        slurm_build_node=CONTAINER_BUILD_NODE,
        simulation_store_base_path=str(remote_base),
    ):
        _provision_remote_tree(env=details.env)
        yield SlurmBackend(
            kind="container",
            partition=CONTAINER_PARTITION,
            qos=CONTAINER_QOS,
            remote_base=remote_base,
            # Measured, not assumed: with the subordinate id range mounted in, the
            # container pulls from a registry, builds a definition file with --fakeroot,
            # and runs the result from inside a SLURM job. What it does not have is the
            # real simulator images, which is why those tests stay cluster_only.
            can_build_singularity=True,
        )
