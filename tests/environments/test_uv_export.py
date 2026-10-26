"""A composed version as uv files (docs/plan-environment-composition.md, step 4b): pins read from pixi.lock, the uv
project constrained to them, uv's lock compared with pixi's, and the Job that locks it."""

import base64
import os
import subprocess
from pathlib import Path

import pytest

from compose_api.environments import uv_export
from compose_api.simulation import build_k8s
from compose_api.simulation.build_k8s import read_inspection_log, uv_lock_script

PIXI_LOCK = """\
version: 7
packages:
- conda: https://conda.anaconda.org/conda-forge/linux-64/python-3.12.15-h5f976f7_2_cpython.conda
  sha256: abc
- pypi: https://files.pythonhosted.org/packages/x/numpy-2.5.4-cp312-manylinux.whl
  name: numpy
  version: 2.5.4
- pypi: git+https://github.com/biosimulations/pbsim_common?rev=26fa156#26fa156
  name: pbsim-common
  version: 0.1.3.dev1
- pypi: https://files.pythonhosted.org/packages/x/Process_Bigraph-1.9.1-py3-none-any.whl
  name: Process_Bigraph
  version: 1.9.1
"""
COMMIT = "26fa156cfab2c309150be818774be4a0c307ce3b"
SPEC = {
    "entries": [
        {"id": "pbsim-common", "install": {"git": "https://github.com/biosimulations/pbsim_common", "commit": COMMIT}},
        {"id": "pyvcell", "install": {"pypi": "pyvcell", "version": "0.5.2", "extras": ["native", "ode"]}},
    ],
    "core": {"process-bigraph": "1.9.1"},
    "python": "3.12",
    "pixi_toml": '[workspace]\nexclude-newer = "2026-10-25T22:00:00Z"\n',
}
UV_LOCK = """\
version = 1
requires-python = "==3.12.*"

[[package]]
name = "numpy"
version = "2.5.4"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pbsim-common"
version = "0.1.3.dev1"
source = { git = "https://github.com/biosimulations/pbsim_common?rev=26fa156#26fa156" }

[[package]]
name = "process-bigraph"
version = "1.9.1"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "registry-env-3"
version = "0"
source = { virtual = "." }
"""


def test_pins_are_every_pypi_package_pixi_resolved_by_normalized_name() -> None:
    assert uv_export.pypi_pins(PIXI_LOCK) == {
        "numpy": "2.5.4",
        "pbsim-common": "0.1.3.dev1",
        "process-bigraph": "1.9.1",
    }


def test_the_project_names_the_entries_and_constrains_everything_else_to_pixis_versions() -> None:
    project = uv_export.pyproject("registry_env", 3, SPEC, uv_export.pypi_pins(PIXI_LOCK))
    assert 'name = "registry-env-3"' in project and 'requires-python = "==3.12.*"' in project
    assert f'"pbsim_common @ git+https://github.com/biosimulations/pbsim_common@{COMMIT}"' in project
    assert '"pyvcell[native,ode]==0.5.2"' in project and '"process-bigraph==1.9.1"' in project
    assert 'constraint-dependencies = ["numpy==2.5.4"]' in project  # direct ones are not constrained twice
    assert "package = false" in project and 'exclude-newer = "2026-10-25T22:00:00Z"' in project
    assert "implementation_name == 'cpython'" in project and "platform_machine == 'x86_64'" in project


def test_uvs_resolution_is_compared_with_pixis() -> None:
    pins = uv_export.pypi_pins(PIXI_LOCK)
    assert uv_export.uv_pins(UV_LOCK) == pins  # the virtual project itself is not a package
    moved = UV_LOCK.replace('version = "2.5.4"', 'version = "2.5.3"')
    assert uv_export.differences(pins, uv_export.uv_pins(moved)) == ["numpy: pixi 2.5.4, uv 2.5.3"]
    extra = UV_LOCK + '\n[[package]]\nname = "cffi"\nversion = "2.1.1"\n'
    assert uv_export.differences(pins, uv_export.uv_pins(extra)) == ["cffi: pixi -, uv 2.1.1"]


def test_only_a_composition_without_conda_has_a_uv_form() -> None:
    assert not uv_export.needs_conda(SPEC)
    assert uv_export.needs_conda({"entries": [{"id": "readdy", "conda": {"readdy": "==2.0.13"}}]})


def test_the_uv_lock_script_prints_the_lock_or_why_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "pixi"
    fake.write_text(
        '#!/bin/bash\n[ "$1 $2 $3 $4 $5" = "exec --spec uv uv lock" ] || exit 2\n'
        'if grep -q conflict pyproject.toml; then echo "No solution for numpy" >&2; exit 1; fi\n'
        'printf "version = 1\\n" > uv.lock\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(build_k8s, "SCRATCH_DIR", str(scratch))
    for project, expected in [("[project]\n", {build_k8s.UV_LOCKED: "version = 1\n"}), ("# conflict\n", None)]:
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            build_k8s.PYPROJECT_ENV: base64.b64encode(project.encode()).decode(),
        }
        result = subprocess.run(  # noqa: S603 the Job's script, rendered from test constants
            ["/bin/bash", "-c", uv_lock_script()], env=env, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        found = read_inspection_log(result.stdout)
        if expected is not None:
            assert found == expected
        else:
            assert list(found) == [build_k8s.UV_ERROR] and "No solution for numpy" in found[build_k8s.UV_ERROR]
