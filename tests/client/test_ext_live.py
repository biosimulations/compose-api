"""The application layer against the deployed service. Replaces compose-api-client 0.2.0's own test, which
submitted a simulation to production on every run; this one only reads, and only under
``--slurm-backend cluster`` (it needs the network path to compose.cam.uchc.edu)."""

import pytest
from compose_api_client.ext import DEFAULT_URL, ComposeSession


@pytest.mark.slurm
@pytest.mark.cluster_only
def test_production_answers_health_and_lists_simulators(request: pytest.FixtureRequest) -> None:
    # The conftest gates cluster_only through the slurm_backend fixture, which this test does not need (no SSH).
    if "cluster" not in request.config.getoption("--slurm-backend"):
        pytest.skip("needs the deployed service: rerun with --slurm-backend cluster")
    with ComposeSession(DEFAULT_URL, timeout=30) as s:
        assert s.health()["version"]
        assert s.simulators() is not None
        assert s.status(0).status == "submitting"  # no simulation 0: a 404, read as "no job yet"
