"""Builds of environments' images on their own (docs/plan-environment-builds.md, phase 4, E5).

A run's preprocess and an independent build (``POST /registry/environments/{name}/build``) go through one function,
``handlers.ensure_image``: an available image is used as it is; otherwise, under the definition's lock, a build run
of the definition that has not finished is joined (it may have been started by another API process, or before a
restart) rather than started again; otherwise the image is pulled or built. This module holds what both sides read:
an environment's definition and simulator, its image status, and the wait on a build run through the database.
"""

import asyncio
import datetime
import logging
from collections.abc import Mapping
from enum import StrEnum

from pbest.utils.input_types import ContainerizationFileRepr
from pydantic import BaseModel, Field

from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseService
from compose_api.db.services.hpc_db import HPCDatabaseService
from compose_api.db.services.simulators_db import SimulatorDatabaseService
from compose_api.registry.environments import EnvironmentSpec, load_environments, offered
from compose_api.simulation import images
from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.models import EnvironmentImage, HpcRun, JobStatus, JobType, SimulatorVersion

logger = logging.getLogger(__name__)

#: How often a waiter reads its build run's status (the job monitor writes it, from any backend).
POLL_SECONDS = 10.0

FINISHED = frozenset({
    JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.OUT_OF_MEMORY, JobStatus.TIMEOUT,
})  # fmt: skip


class BuildFailedError(RuntimeError):
    pass


class ImageState(StrEnum):
    AVAILABLE = "available"  # an available image: runs use it
    BUILDING = "building"  # a build run of the definition has not finished
    FAILED = "failed"  # the newest build failed, and no image is available
    MISSING = "missing"  # never built, or its image is gone


class ImageStatus(BaseModel):
    """Whether a simulator's image is there to run from, and the records behind that answer."""

    simulator_id: int
    container_def_hash: str
    environment: str | None = Field(default=None, description="The environment whose current definition this is")
    state: ImageState
    image: EnvironmentImage | None = Field(default=None, description="The available image runs use")
    build: HpcRun | None = Field(default=None, description="The newest build run of the definition")
    images: list[EnvironmentImage] = Field(default_factory=list, description="Every image recorded, newest first")


def find_environment(name: str, prebuilt: Mapping[str, str]) -> EnvironmentSpec | None:
    """An environment this deployment offers, by name (``prebuilt``: ``environments.versions.prebuilt_images``)."""
    spec = next((e for e in load_environments().environments if e.name == name), None)
    return spec if spec is not None and offered(spec, prebuilt) else None


async def simulator_for(
    simulator_db: SimulatorDatabaseService, definition: ContainerizationFileRepr
) -> SimulatorVersion:
    """The simulator of a definition, created the first time it is needed (as a run's submission does)."""
    found = await simulator_db.get_simulator_by_def_hash(get_singularity_hash(definition))
    return found if found is not None else await simulator_db.insert_simulator(definition)


async def image_status(
    database_service: DatabaseService, simulator: SimulatorVersion, environment: str | None = None
) -> ImageStatus:
    """The simulator's image as it stands, checked against the store; nothing is started."""
    simulator_db = database_service.get_simulator_db()
    if images.tracked():
        image = await images.available_sif(simulator_db, simulator)
    else:
        image = None
    build = await database_service.get_hpc_db().get_hpcrun_by_ref(
        ref_id=simulator.database_id, job_type=JobType.BUILD_CONTAINER
    )
    if image is not None:
        state = ImageState.AVAILABLE
    elif build is not None and build.status not in FINISHED:
        state = ImageState.BUILDING
    elif build is not None and build.status != JobStatus.COMPLETED:
        state = ImageState.FAILED
    else:
        state = ImageState.MISSING
    return ImageStatus(
        simulator_id=simulator.database_id,
        container_def_hash=simulator.container_def_hash,
        environment=environment,
        state=state,
        image=image,
        build=build,
        images=await simulator_db.list_images(simulator.database_id),
    )


def build_timeout_seconds(backend: str) -> int:
    """How long a waiter gives a build run: the Job's own deadline on Kubernetes, the SLURM build's time limit."""
    return get_settings().build_k8s_timeout_seconds + 300 if backend == "k8s" else 3600


async def wait_for_run(run: HpcRun, hpc_db: HPCDatabaseService) -> HpcRun:
    """Wait for a build run to finish, reading its status in the database (the job monitor updates it, from any
    backend, so any API process may wait on a build another started). `BuildFailedError` unless it completed."""
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=build_timeout_seconds(run.backend))
    current: HpcRun | None = run
    while current is not None and current.status not in FINISHED and datetime.datetime.now() < deadline:
        await asyncio.sleep(POLL_SECONDS)
        current = await hpc_db.get_hpcrun(run.database_id)
    if current is not None and current.status == JobStatus.COMPLETED:
        return current
    status = "missing" if current is None else (current.status or "unknown")
    if current is not None and current.status not in FINISHED:
        status = f"still {status} after {build_timeout_seconds(run.backend)} s"
    raise BuildFailedError(f"Build run {run.database_id} ({run.backend} {run.external_id}) {status}")
