import logging
from abc import ABC, abstractmethod
from pathlib import Path

import numpy
from pydantic import BaseModel
from typing_extensions import override

from compose_api.common.gateway.models import Namespace
from compose_api.common.ssh.ssh_service import SSHService, get_custom_ssh_service
from compose_api.config import Settings, get_settings
from compose_api.simulation.hpc_utils import get_internal_experiment_dir

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

assets_dir = Path(get_settings().assets_dir)


class DataService(ABC):
    settings: Settings

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def ssh_service(self) -> SSHService:
        return get_custom_ssh_service(settings=self.settings)

    @abstractmethod
    async def get_results_zip(self, experiment_id: str, namespace: Namespace) -> Path:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class DataServiceHpc(DataService):
    @override
    async def get_results_zip(self, experiment_id: str, namespace: Namespace) -> Path:
        return Path(f"{get_internal_experiment_dir(experiment_id=experiment_id, namespace=namespace)}/results.zip")

    @override
    async def close(self) -> None:
        pass


class PackedArray(BaseModel):
    shape: tuple[int, int]
    values: list[float]

    def hydrate(self) -> numpy.ndarray:
        return numpy.array(self.values).reshape(self.shape)


def pack_array(arr: numpy.ndarray) -> PackedArray:
    return PackedArray(shape=arr.shape, values=arr.flatten().tolist())
