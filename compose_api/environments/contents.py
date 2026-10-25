"""What an environment version's image installed and provides (docs/plan-environment-versions.md, V7, steps 4b-4c).

The build Job reads them from the image it made (``build_k8s.inspect_script``) and places them beside it, as
``<hash>.installed.txt`` and ``<hash>.interfaces.json``. They are stored on the version when an administrator's build
finishes, and otherwise the first time a ready version without them is read: a version an implicit build made (a
run's) gets them too. Where the store is not mounted here, or a file was not written, nothing is stored.

A prebuilt version's image is pulled, not built, so it is read by a Job of its own that runs the image unprivileged
and prints the same two files (``build_k8s.inspection_job``).
"""

import json
import logging
import uuid
from typing import Any

from compose_api.db.database_service import DatabaseService
from compose_api.simulation import images
from compose_api.simulation.build_k8s import INSPECTIONS
from compose_api.simulation.hpc_utils import get_image_inspection_file
from compose_api.simulation.models import EnvironmentVersion

logger = logging.getLogger(__name__)


def _read(singularity_hash: str, kind: str) -> str | None:
    path = images.internal_path(str(get_image_inspection_file(singularity_hash, kind)))
    if path is None:
        return None
    try:
        return path.read_text()
    except (FileNotFoundError, UnicodeDecodeError):
        return None


def _parse(version: EnvironmentVersion, files: dict[str, str]) -> tuple[str | None, dict[str, Any] | None]:
    interfaces: dict[str, Any] | None = None
    if (text := files.get("interfaces.json")) is not None:
        try:
            interfaces = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"{version.label}'s interfaces are not JSON; left out")
    return files.get("installed.txt"), interfaces


async def inspect_prebuilt_version(database_service: DatabaseService, version: EnvironmentVersion) -> bool:
    """Run a prebuilt version's image in a Job of its own to read what it installed and provides (step 4c), and
    store them; whether anything was read."""
    from compose_api.simulation.build_k8s import inspect_prebuilt, inspection_of

    inspection = await inspection_of(version)
    if version.image is None or inspection is None:
        return False
    files = await inspect_prebuilt(version.image, inspection, uuid.uuid4().hex[:5])
    installed, interfaces = _parse(version, files)
    if installed is None and interfaces is None:
        logger.warning(f"Reading back {version.label} ({version.image}) found nothing")
        return False
    await database_service.get_environments_db().set_contents(version.database_id, installed, interfaces)
    return True


async def record_contents(database_service: DatabaseService, version: EnvironmentVersion) -> bool:
    """Store what the version's image installed and provides, if the build left them; whether anything was."""
    simulator = await database_service.get_simulator_db().get_simulator(version.simulator_id)
    if simulator is None:
        return False
    files = {kind: text for kind in INSPECTIONS if (text := _read(simulator.container_def_hash, kind)) is not None}
    installed, interfaces = _parse(version, files)
    if installed is None and interfaces is None:
        return False
    await database_service.get_environments_db().set_contents(version.database_id, installed, interfaces)
    return True
