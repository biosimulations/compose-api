"""What an environment version's image installed and provides (docs/plan-environment-versions.md, V7, step 4b).

The build Job reads them from the image it made (``build_k8s.inspect_script``) and places them beside it, as
``<hash>.installed.txt`` and ``<hash>.interfaces.json``. They are stored on the version when an administrator's build
finishes, and otherwise the first time a ready version without them is read: a version an implicit build made (a
run's) gets them too. Where the store is not mounted here, or a file was not written, nothing is stored.
"""

import json
import logging
from typing import Any

from compose_api.db.database_service import DatabaseService
from compose_api.simulation import images
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


async def record_contents(database_service: DatabaseService, version: EnvironmentVersion) -> bool:
    """Store what the version's image installed and provides, if the build left them; whether anything was."""
    simulator = await database_service.get_simulator_db().get_simulator(version.simulator_id)
    if simulator is None:
        return False
    installed = _read(simulator.container_def_hash, "installed.txt")
    interfaces: dict[str, Any] | None = None
    if (text := _read(simulator.container_def_hash, "interfaces.json")) is not None:
        try:
            interfaces = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"{version.label}'s interfaces are not JSON; left out")
    if installed is None and interfaces is None:
        return False
    await database_service.get_environments_db().set_contents(version.database_id, installed, interfaces)
    return True
