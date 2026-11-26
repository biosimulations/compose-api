"""The SLURM backend's settings are in force only for a test that takes ``slurm_backend`` (#583)."""

from pathlib import Path

import pytest

from compose_api.config import get_settings, override_settings
from tests.fixtures.slurm_fixtures_backend import SelectedBackend, SlurmBackend


@pytest.mark.slurm
def test_a_test_that_takes_the_backend_runs_on_its_settings(slurm_backend: SlurmBackend) -> None:
    assert Path(get_settings().simulation_store_base_path) == slurm_backend.remote_base


@pytest.mark.slurm
def test_after_it_a_test_that_does_not_may_set_them_itself(
    selected_slurm_backend: SelectedBackend, tmp_path: Path
) -> None:
    # The cluster is still up for the session; its settings must not be. A layer left over from the session or
    # from the test above makes this raise, as it did for the staging and contents tests in one `make test`.
    with override_settings(simulation_store_base_path=str(tmp_path)):
        assert get_settings().simulation_store_base_path == str(tmp_path)
