"""A shared version's lock and definition (docs/plan-environment-versions.md, step 3): resolved once with nothing
newer than its date, its hash the identity, and the definition installing exactly it with pbest's runtime unchanged.

The compile tests ask PyPI (through uv) about ``six``, whose releases are years old, so their answers do not move."""

import datetime
import shutil

import pytest
from pbest.containerization.container_constructor import generate_container_def_file
from pbest.utils.input_types import ContainerizationEngine

from compose_api.environments.definition import ENV_PATH, shared_definition
from compose_api.environments.lock import Lock, LockError, SharedSpec, changes, compile_lock, exclude_newer, pins
from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.simulator_registry import registry_dependencies, registry_libraries

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")

SIX = SharedSpec(libraries=[{"name": "six", "package_registry": "pypi"}])
BEFORE_SIX_1_11 = datetime.datetime(2016, 1, 1)  # six 1.10.0 is from 2015-10; 1.11.0 from 2017-09


def _runscript(definition: str) -> str:
    return definition[definition.index("%runscript") :]


@needs_uv
@pytest.mark.asyncio
async def test_a_lock_holds_nothing_newer_than_its_date_and_is_the_same_each_time() -> None:
    first = await compile_lock(SIX, BEFORE_SIX_1_11)
    assert "six==1.10.0" in first.text.splitlines()
    second = await compile_lock(SIX, BEFORE_SIX_1_11)
    assert (second.text, second.sha256) == (first.text, first.sha256)
    later = await compile_lock(SIX, datetime.datetime(2018, 1, 1))
    assert "six==1.11.0" in later.text.splitlines() and later.sha256 != first.sha256


@needs_uv
@pytest.mark.asyncio
async def test_a_spec_uv_cannot_resolve_is_a_lock_error_with_uvs_reason() -> None:
    impossible = SharedSpec(libraries=[{"name": "six", "version": "99.0.0", "package_registry": "pypi"}])
    with pytest.raises(LockError, match="six"):
        await compile_lock(impossible, BEFORE_SIX_1_11)


def test_the_registry_spec_pins_its_libraries_and_the_pbest_runtime() -> None:
    spec = SharedSpec.from_registry()
    assert spec.libraries == registry_libraries()
    assert "pyvcell[native,ode]==0.5.2" in spec.pypi()
    assert spec.pypi()[-1] == f"pbest @ git+https://github.com/biosimulations/pbest@{spec.pbest}"
    assert spec.conda() == ["readdy=2.0.13"]
    assert spec.as_json() == {"libraries": registry_libraries(), "pbest": spec.pbest}


def test_the_date_is_given_to_uv_in_utc() -> None:
    assert exclude_newer(datetime.datetime(2026, 10, 25, 18)) == "2026-10-25T18:00:00Z"
    eastern = datetime.timezone(datetime.timedelta(hours=-4))
    assert exclude_newer(datetime.datetime(2026, 10, 25, 14, tzinfo=eastern)) == "2026-10-25T18:00:00Z"


def test_the_definition_installs_exactly_the_lock_and_keeps_pbests_runtime() -> None:
    spec = SharedSpec.from_registry()
    lock = Lock(text="six==1.10.0\n    # via -r spec.in\n", resolved_at=BEFORE_SIX_1_11)
    definition = shared_definition(spec, lock).representation
    assert "<<'COMPOSE_API_LOCK'\nsix==1.10.0\n    # via -r spec.in\nCOMPOSE_API_LOCK\n" in definition
    assert f"uv pip install --python {ENV_PATH}/bin/python --no-deps -r /runtime/environment.lock" in definition
    assert f"micromamba create -p {ENV_PATH} -c conda-forge python=3.12 readdy=2.0.13 --yes" in definition
    assert f"git clone --branch {spec.pbest} https://github.com/biosimulations/pbest.git /runtime" in definition
    # the job script drives the image exactly as it drove pbest's (runtime contract 1)
    pbest = generate_container_def_file(registry_dependencies(), ContainerizationEngine.APPTAINER).representation
    assert _runscript(definition).split() == _runscript(pbest).split()


def test_the_definitions_hash_follows_the_lock() -> None:
    spec = SharedSpec.from_registry()
    one = Lock(text="six==1.10.0\n", resolved_at=BEFORE_SIX_1_11)
    other = Lock(text="six==1.11.0\n", resolved_at=BEFORE_SIX_1_11)
    assert get_singularity_hash(shared_definition(spec, one)) == get_singularity_hash(shared_definition(spec, one))
    assert get_singularity_hash(shared_definition(spec, one)) != get_singularity_hash(shared_definition(spec, other))


def test_a_shared_definition_needs_the_pbest_runtime() -> None:
    with pytest.raises(ValueError, match="pbest"):
        shared_definition(SIX, Lock(text="six==1.10.0\n", resolved_at=BEFORE_SIX_1_11))


def test_a_locks_packages_are_read_by_normalized_name_and_compared() -> None:
    old = "Pb_Multiscale.Actin==1.3.1\n    # via -r spec.in\nnumpy==2.4.0\npbest @ git+https://x/pbest@a\n"
    new = "pb-multiscale-actin==1.3.1\nnumpy==2.5.4\npbest @ git+https://x/pbest@b\nlibvcell==0.0.24\n"
    assert pins(old) == {"pb-multiscale-actin": "1.3.1", "numpy": "2.4.0", "pbest": "git+https://x/pbest@a"}
    assert changes(old, new) == [
        ("libvcell", None, "0.0.24"),
        ("numpy", "2.4.0", "2.5.4"),
        ("pbest", "git+https://x/pbest@a", "git+https://x/pbest@b"),
    ]
