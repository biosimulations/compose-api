import tempfile
from pathlib import Path

from compose_api.common.gateway.models import Namespace
from compose_api.config import get_settings
from compose_api.simulation.data_service import DataService
from compose_api.simulation.hpc_utils import get_slurm_sim_results_file_path


class TestDataService(DataService):
    settings = get_settings()

    async def get_results_zip(self, experiment_id: str, namespace: Namespace) -> Path:
        remote_experiment_result = get_slurm_sim_results_file_path(experiment_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix="results_") as tmp_file:
            await self.ssh_service.scp_download(Path(tmp_file.name), Path(remote_experiment_result))
            return Path(tmp_file.name)

    async def close(self) -> None:
        pass
