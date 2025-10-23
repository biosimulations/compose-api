import asyncio
import tempfile
from pathlib import Path
from types import CoroutineType, FunctionType
from typing import Annotated, Any, Callable

from fastapi import BackgroundTasks
from typing_extensions import Doc, ParamSpec

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


Pam = ParamSpec("Pam")


class TestBackgroundTask(BackgroundTasks):
    tasks_to_execute: list[Any] = []

    def add_task(
        self,
        func: Annotated[
            Callable[Pam, Any],
            Doc(
                """
                The function to call after the response is sent.

                It can be a regular `def` function or an `async def` function.
                """
            ),
        ],
        *args: Pam.args,
        **kwargs: Pam.kwargs,
    ) -> None:
        self.tasks_to_execute.append(func)

    async def call_tasks(self) -> None:
        while len(self.tasks_to_execute) > 0:
            func: FunctionType | CoroutineType[Any, Any, Any] = self.tasks_to_execute.pop(0)
            if asyncio.iscoroutinefunction(func):
                await func()
            elif isinstance(func, FunctionType):
                func()
            else:
                raise TypeError(f"Unexpected type {type(func)}")
