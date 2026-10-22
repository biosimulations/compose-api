"""Staging a queued run's files (compose_api/simulation/staging.py)."""

import stat
from pathlib import Path

import pytest

from compose_api.config import override_settings
from compose_api.simulation import staging
from compose_api.simulation.hpc_utils import get_slurm_staging_dir
from compose_api.simulation.models import SimulationFileType, SimulationRequest


@pytest.fixture
def request_files(tmp_path: Path) -> SimulationRequest:
    (tmp_path / "upload.omex").write_bytes(b"translated")
    (tmp_path / "original.omex").write_bytes(b"original")
    return SimulationRequest(
        request_file_path=tmp_path / "upload.omex",
        source_file_path=tmp_path / "original.omex",
        simulation_file_type=SimulationFileType.OMEX,
        is_batch=False,
    )


def _store(tmp_path: Path) -> dict[str, str]:
    mount = tmp_path / "mount"
    mount.mkdir()
    return {"simulation_store_base_path": "/projects/store", "internal_mount_dir": str(mount)}


def test_on_the_store_the_paths_are_the_clusters_and_the_files_world_readable(
    tmp_path: Path, request_files: SimulationRequest
) -> None:
    with override_settings(**_store(tmp_path), namespace="test"):
        staged, on_store = staging.stage_request(request_files, "exp1")
        cluster_dir = get_slurm_staging_dir("exp1")
    assert on_store
    assert staged.request_file_path == cluster_dir / "exp1.omex"
    assert staged.source_file_path == cluster_dir / "source.omex"
    local = tmp_path / "mount" / "test" / "staging" / "exp1"
    assert (local / "exp1.omex").read_bytes() == b"translated"
    assert (local / "source.omex").read_bytes() == b"original"
    assert stat.S_IMODE((local / "exp1.omex").stat().st_mode) == 0o644
    assert stat.S_IMODE(local.stat().st_mode) == 0o755  # the SLURM service user copies from here


def test_without_the_store_files_are_staged_locally(tmp_path: Path, request_files: SimulationRequest) -> None:
    with override_settings(submission_staging_dir=str(tmp_path / "local"), internal_mount_dir=str(tmp_path / "none")):
        staged, on_store = staging.stage_request(request_files, "exp2")
    assert not on_store
    assert staged.request_file_path == tmp_path / "local" / "exp2" / "exp2.omex"
    assert staged.request_file_path.read_bytes() == b"translated"


def test_a_store_that_refuses_the_write_falls_back_to_local_staging(
    tmp_path: Path, request_files: SimulationRequest
) -> None:
    settings = _store(tmp_path)
    (tmp_path / "mount" / "test").mkdir()
    (tmp_path / "mount" / "test").chmod(0o555)  # the API's user may not create staging/ here
    try:
        with override_settings(**settings, namespace="test", submission_staging_dir=str(tmp_path / "local")):
            staged, on_store = staging.stage_request(request_files, "exp3")
    finally:
        (tmp_path / "mount" / "test").chmod(0o755)
    assert not on_store
    assert staged.request_file_path.read_bytes() == b"translated"
