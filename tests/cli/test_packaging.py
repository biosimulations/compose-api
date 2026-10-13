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
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Iterator[zipfile.ZipFile]:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv builds the wheel; it is not on PATH")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(  # noqa: S603
        [uv, "build", "--wheel", "--out-dir", str(out)], cwd=ROOT, check=True, capture_output=True, timeout=300
    )
    [built] = out.glob("compose_api-*.whl")
    with zipfile.ZipFile(built) as archive:
        yield archive


def _metadata(wheel: zipfile.ZipFile, name: str) -> str:
    [path] = [entry for entry in wheel.namelist() if entry.endswith(f".dist-info/{name}")]
    return wheel.read(path).decode()


def test_the_wheel_declares_the_console_script(wheel: zipfile.ZipFile) -> None:
    entry_points = _metadata(wheel, "entry_points.txt")
    assert "[console_scripts]\ncompose-api = compose_api.cli.main:main" in entry_points


def test_the_wheel_carries_every_cli_module(wheel: zipfile.ZipFile) -> None:
    shipped = set(wheel.namelist())
    modules = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "compose_api" / "cli").rglob("*.py"))
    assert modules and [module for module in modules if module not in shipped] == []


def test_the_wheel_declares_the_floor_and_the_cli_dependencies(wheel: zipfile.ZipFile) -> None:
    metadata = _metadata(wheel, "METADATA")
    assert "Requires-Python: <4.0,>=3.13.2" in metadata
    for dependency in ("authlib", "joserfc", "keyring", "portalocker", "platformdirs", "pyjwt", "httpx", "attrs"):
        assert re.search(rf"^Requires-Dist: {dependency}\b", metadata, re.MULTILINE | re.IGNORECASE), dependency


def test_the_wheel_contains_nothing_secret_shaped(wheel: zipfile.ZipFile) -> None:
    assert [name for name in wheel.namelist() if SECRET_SHAPED.search(name)] == []
