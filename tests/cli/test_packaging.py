"""The built wheel: the console script, every CLI module, the declared floor and dependencies, and nothing secret.

The installed entry point itself is exercised by `test_commands.py`; this builds the artefact a release would publish.
"""

import re
import shutil
import subprocess
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from compose_api.config import REPO_ROOT

ROOT = Path(REPO_ROOT)
# Files that must never be packaged: dotenv files, keys and certificates, and a CLI profile.
SECRET_SHAPED = re.compile(r"(^|/)(\.env|\.dev_env|[^/]*_env|id_rsa[^/]*|config\.toml)$|\.(pem|key|p12|pfx|crt)$")


@pytest.fixture(scope="module")
def client_wheel(tmp_path_factory: pytest.TempPathFactory) -> Iterator[zipfile.ZipFile]:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv builds the wheel; it is not on PATH")
    out = tmp_path_factory.mktemp("dist-client")
    subprocess.run(  # noqa: S603
        [uv, "build", "--package", "compose-api-client", "--wheel", "--out-dir", str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=300,
    )
    [built] = out.glob("compose_api_client-*.whl")
    with zipfile.ZipFile(built) as archive:
        yield archive


@pytest.fixture(scope="module")
def root_wheel(tmp_path_factory: pytest.TempPathFactory) -> Iterator[zipfile.ZipFile]:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv builds the wheel; it is not on PATH")
    out = tmp_path_factory.mktemp("dist-root")
    subprocess.run(  # noqa: S603
        [uv, "build", "--wheel", "--out-dir", str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=300,
    )
    [built] = out.glob("compose_api-*.whl")
    with zipfile.ZipFile(built) as archive:
        yield archive


def _metadata(wheel: zipfile.ZipFile, name: str) -> str:
    [path] = [entry for entry in wheel.namelist() if entry.endswith(f".dist-info/{name}")]
    return wheel.read(path).decode()


def test_the_wheel_declares_the_console_script(client_wheel: zipfile.ZipFile, root_wheel: zipfile.ZipFile) -> None:
    entry_points = _metadata(client_wheel, "entry_points.txt")
    assert "[console_scripts]\ncompose-api = compose_api_client.cli:main" in entry_points
    root_entry_points = [entry for entry in root_wheel.namelist() if entry.endswith(".dist-info/entry_points.txt")]
    assert root_entry_points == []


def test_the_wheel_carries_every_cli_module(client_wheel: zipfile.ZipFile) -> None:
    shipped = set(client_wheel.namelist())
    client_root = ROOT / "clients" / "python"
    modules = sorted(
        path.relative_to(client_root).as_posix() for path in (client_root / "compose_api_client").rglob("*.py")
    )
    assert modules and [module for module in modules if module not in shipped] == []


def test_the_wheel_declares_the_floor_and_the_cli_dependencies(client_wheel: zipfile.ZipFile) -> None:
    metadata = _metadata(client_wheel, "METADATA")
    assert "Requires-Python: >=3.11" in metadata
    for dependency in ("authlib", "joserfc", "keyring", "portalocker", "platformdirs", "pyjwt", "httpx", "attrs"):
        assert re.search(rf"^Requires-Dist: {dependency}\b", metadata, re.MULTILINE | re.IGNORECASE), dependency


def test_the_wheel_contains_nothing_secret_shaped(client_wheel: zipfile.ZipFile, root_wheel: zipfile.ZipFile) -> None:
    assert [name for name in client_wheel.namelist() if SECRET_SHAPED.search(name)] == []
    assert [name for name in root_wheel.namelist() if SECRET_SHAPED.search(name)] == []
