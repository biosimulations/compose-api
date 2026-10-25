"""Which environment version a run uses (docs/plan-environment-versions.md, step 2).

Until versions are created through the API (step 4), the deployment decides, as it decided the image before: the
shared environment runs the definition generated from the pinned library list (``simulator_registry.json``), a
prebuilt one the definition of its pinned image (``settings.prebuilt_simulators``). That definition's version is
made the environment's default, and is created, as the next number, the first time it is seen. So a deploy that
changes either still changes what runs, a rollback returns to the earlier version rather than adding one, and every
run records the version it used.
"""

from typing import TYPE_CHECKING

from pbest.containerization.container_constructor import generate_container_def_file
from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

from compose_api.registry.environments import load_environments
from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.models import EnvironmentVersion, SimulatorVersion
from compose_api.simulation.prebuilt import prebuilt_definition, prebuilt_image
from compose_api.simulation.simulator_registry import registry_dependencies, registry_libraries

if TYPE_CHECKING:
    from compose_api.db.database_service import DatabaseService


def shared_environment() -> str:
    """The shared environment's name (``registry_env``)."""
    return next(e.name for e in load_environments().environments if e.kind == "shared")


def deployed_definition(simulator: str | None) -> tuple[ContainerizationFileRepr, str | None]:
    """The definition this deployment runs ``simulator`` from (a prebuilt simulator's name, or None for the shared
    environment), and a prebuilt one's image. `UnknownSimulatorError` for a name the deployment does not list."""
    if simulator is None:
        return generate_container_def_file(registry_dependencies(), ContainerizationEngine.APPTAINER), None
    image = prebuilt_image(simulator)
    return prebuilt_definition(image), image


async def version_for(
    database_service: "DatabaseService", simulator: str | None
) -> tuple[EnvironmentVersion, SimulatorVersion]:
    """The version a run of ``simulator`` uses (None: the shared environment), and its simulator row, both created
    the first time the deployment's definition is seen."""
    definition, image = deployed_definition(simulator)
    simulator_db = database_service.get_simulator_db()
    found = await simulator_db.get_simulator_by_def_hash(get_singularity_hash(definition))
    simulator_version = found if found is not None else await simulator_db.insert_simulator(definition)
    environments_db = database_service.get_environments_db()
    if simulator is None:
        version = await environments_db.adopt_deployed(
            shared_environment(),
            "shared",
            simulator_version.database_id,
            spec={"libraries": registry_libraries()},
            origin="registry",
        )
    else:
        version = await environments_db.adopt_deployed(
            simulator, "prebuilt", simulator_version.database_id, image=image
        )
    return version, simulator_version
