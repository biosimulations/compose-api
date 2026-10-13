"""Simulators' images as artifacts (docs/plan-environment-builds.md, phase 2).

A simulator's SIF lives at ``<store>/<namespace>/images/<hash>.sif`` on the shared filesystem, the path its jobs run
from. Each one is recorded in ``environment_image`` (E3): "built" means an available record, checked against the file
through the API's own mount of the store (``settings.internal_mount_dir``). A file with no record (built before the
records, or pulled) is adopted (E4); a record whose file is gone is marked unavailable, and the run path fetches the
image again.

Where the store is not mounted (development, tests), records are trusted as they are.
"""

import asyncio
import hashlib
import logging
from pathlib import Path

from pbest.utils.input_types import ContainerizationEngine

from compose_api.config import get_settings
from compose_api.db.services.simulators_db import SimulatorDatabaseService
from compose_api.simulation.hpc_utils import get_slurm_singularity_container_file
from compose_api.simulation.models import EnvironmentImage, ImageKind, SimulatorVersion

logger = logging.getLogger(__name__)

_CHUNK = 8 * 1024 * 1024


def tracked() -> bool:
    """Images are recorded where jobs run from SIF files (Apptainer); a Docker engine pulls by tag instead."""
    return get_settings().container_service == ContainerizationEngine.APPTAINER.name


def sif_location(simulator: SimulatorVersion) -> str:
    """The SIF's path on the cluster, as the job scripts name it."""
    return str(get_slurm_singularity_container_file(singularity_hash=simulator.container_def_hash))


def store_mounted() -> bool:
    """Whether this process sees the store, through ``settings.internal_mount_dir``."""
    settings = get_settings()
    return bool(settings.simulation_store_base_path) and Path(settings.internal_mount_dir).is_dir()


def internal_path(location: str) -> Path | None:
    """The API's view of a path on the store, or None where the store is not mounted here."""
    base = get_settings().simulation_store_base_path
    if not store_mounted() or not Path(location).is_relative_to(base):
        return None
    return Path(get_settings().internal_mount_dir) / Path(location).relative_to(base)


def _size(path: Path) -> int | None:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    return size if size > 0 else None


def _inspect(path: Path) -> tuple[str, int] | None:
    size = _size(path)
    if size is None:
        return None
    sha = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            sha.update(chunk)
    return f"sha256:{sha.hexdigest()}", size


async def record_sif(
    simulator_db: SimulatorDatabaseService, simulator: SimulatorVersion, hpcrun_id: int | None = None
) -> EnvironmentImage | None:
    """Record the simulator's SIF as available, with its digest and size; None when there is no file to record."""
    location = sif_location(simulator)
    path = internal_path(location)
    if path is None:
        return await simulator_db.record_image(simulator.database_id, ImageKind.SIF, location, hpcrun_id=hpcrun_id)
    found = await asyncio.to_thread(_inspect, path)
    if found is None:
        return None
    digest, size = found
    return await simulator_db.record_image(
        simulator.database_id, ImageKind.SIF, location, digest=digest, size_bytes=size, hpcrun_id=hpcrun_id
    )


async def available_sif(simulator_db: SimulatorDatabaseService, simulator: SimulatorVersion) -> EnvironmentImage | None:
    """The simulator's available SIF, checked against the file: adopted if unrecorded, marked unavailable if gone."""
    location = sif_location(simulator)
    image = await simulator_db.get_available_image(simulator.database_id, ImageKind.SIF)
    path = internal_path(location)
    if path is None:
        return image
    size = await asyncio.to_thread(_size, path)
    if size is None:
        if image is not None:
            logger.warning(f"Image {image.location} of simulator {simulator.database_id} is gone; marked unavailable")
            await simulator_db.set_image_verified(image.database_id, available=False)
        return None
    if image is not None and image.location == location and image.size_bytes in (None, size):
        await simulator_db.set_image_verified(image.database_id, available=True)
        return image
    logger.info(f"Adopting the unrecorded image {location} of simulator {simulator.database_id}")
    return await record_sif(simulator_db, simulator)


async def verify_images(simulator_db: SimulatorDatabaseService) -> dict[str, int]:
    """Check every Apptainer simulator's SIF: adopt the unrecorded (the backfill), mark the missing unavailable."""
    counts = {"available": 0, "missing": 0}
    for simulator in await simulator_db.list_simulators():
        if simulator.container_def.containerization_engine != ContainerizationEngine.APPTAINER:
            continue
        found = await available_sif(simulator_db, simulator)
        counts["available" if found is not None else "missing"] += 1
    return counts


async def verify_images_periodically(simulator_db: SimulatorDatabaseService, interval_seconds: float) -> None:
    """Verify at startup, then every ``interval_seconds``; a failed pass is logged and the next one tried."""
    while True:
        try:
            if tracked() and store_mounted():
                logger.info(f"Image verification: {await verify_images(simulator_db)}")
        except Exception:
            logger.exception("Image verification failed")
        await asyncio.sleep(interval_seconds)
