"""Which environment version a run uses (docs/plan-environment-versions.md, steps 2 and 5).

A run may name its version (step 5): ``registry_env@3``, or ``registry_env@default``, which is resolved to the
default's number when the run is recorded, so what is stored is always a number. A suite run must name one for every
environment its solvers use (``default`` names them all at their defaults).

A version is a database record (docs/plan-environment-composition.md, D8.1): a run that names none takes its
environment's default, which an administrator chose; a shared environment with none yet (a fresh deployment) refuses
the run until one is made (`compose-api environments create registry_env`). Versions made before, pbest's
registry_env@1 among them, stay runnable by number (D8.2). A prebuilt environment's default is still the definition of
its pinned image (``settings.prebuilt_simulators``), created the first time it is seen, until step 8b.
"""

from typing import TYPE_CHECKING

from pbest.utils.input_types import ContainerizationFileRepr

from compose_api.registry.environments import load_environments
from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.models import EnvironmentVersion, SimulatorVersion, VersionState
from compose_api.simulation.prebuilt import prebuilt_definition, prebuilt_image

if TYPE_CHECKING:
    from compose_api.db.database_service import DatabaseService


def shared_environment() -> str:
    """The shared environment's name (``registry_env``)."""
    return next(e.name for e in load_environments().environments if e.kind == "shared")


def deployed_definition(simulator: str) -> tuple[ContainerizationFileRepr, str]:
    """The definition this deployment runs a prebuilt simulator from, and its pinned image. `UnknownSimulatorError`
    for a name the deployment does not list."""
    image = prebuilt_image(simulator)
    return prebuilt_definition(image), image


class VersionUnavailableError(LookupError):
    """A run names a version that does not exist, or that cannot run (failed, retired)."""


class NoDefaultVersionError(VersionUnavailableError):
    """An environment has no default version yet (a fresh deployment, D8.1): an administrator makes one."""


#: the states a run may use: a version still building is waited for, like any image
RUNNABLE = frozenset({VersionState.READY, VersionState.BUILDING})


def environment_of(simulator: str | None) -> str:
    """The environment a run of ``simulator`` (a prebuilt simulator's name, or None) runs in."""
    return simulator if simulator is not None else shared_environment()


async def chosen_version(
    database_service: "DatabaseService", environment: str, number: int
) -> tuple[EnvironmentVersion, SimulatorVersion]:
    """``environment@number`` and its simulator, if a run may use it; `VersionUnavailableError` otherwise."""
    version = await database_service.get_environments_db().get_by_number(environment, number)
    if version is None:
        raise VersionUnavailableError(f"there is no version {environment}@{number}")
    if version.state not in RUNNABLE:
        raise VersionUnavailableError(f"{version.label} is {version.state}: runs cannot use it")
    if version.simulator_id is None:  # not runnable, so not reached: a resolving version has no simulator yet
        raise VersionUnavailableError(f"{version.label} is still resolving")
    simulator = await database_service.get_simulator_db().get_simulator(version.simulator_id)
    if simulator is None:
        raise VersionUnavailableError(f"{version.label}'s simulator {version.simulator_id} is gone")
    plain = version.model_dump(exclude={"lock", "installed", "interfaces"})
    return EnvironmentVersion.model_validate(plain), simulator


def declared(environment: str) -> bool:
    """Whether environments.yaml declares the environment (the shared one, a prebuilt image); a mash-up it does not."""
    return any(spec.name == environment for spec in load_environments().environments)


async def composed_version(
    database_service: "DatabaseService", environment: str, number: int | None = None
) -> tuple[EnvironmentVersion, SimulatorVersion]:
    """The version a run in an undeclared composed environment (a mash-up) uses: ``number``, or its default. The
    deployment has no definition of it, so there is nothing to adopt: its versions are made by composing its entries
    (docs/plan-environment-composition.md, step 7b)."""
    if number is None:
        default = await database_service.get_environments_db().get_default(environment)
        if default is None:
            raise VersionUnavailableError(f"{environment} has no default version yet")
        number = default.number
    return await chosen_version(database_service, environment, number)


async def version_for(
    database_service: "DatabaseService",
    simulator: str | None,
    number: int | None = None,
    environment: str | None = None,
) -> tuple[EnvironmentVersion, SimulatorVersion]:
    """The version a run of ``simulator`` uses (None: the shared environment), and its simulator row: ``number`` when
    the run names one; otherwise the environment's default (D8.1; a prebuilt one's is still adopted from its pinned
    image until step 8b). ``environment`` names an undeclared composed environment (a mash-up) instead.
    `NoDefaultVersionError` when the shared environment has no version yet."""
    if environment is not None and not declared(environment):
        return await composed_version(database_service, environment, number)
    if environment is not None and simulator is None and environment != shared_environment():
        simulator = environment  # a declared prebuilt environment, named as an environment
    if number is not None:
        return await chosen_version(database_service, environment_of(simulator), number)
    if simulator is None:
        shared = shared_environment()
        default = await database_service.get_environments_db().get_default(shared)
        if default is None:
            raise NoDefaultVersionError(
                f"{shared} has no version yet: an administrator makes its first one"
                f" (`compose-api environments create {shared}`)"
            )
        return await chosen_version(database_service, shared, default.number)
    definition, image = deployed_definition(simulator)
    simulator_db = database_service.get_simulator_db()
    found = await simulator_db.get_simulator_by_def_hash(get_singularity_hash(definition))
    simulator_version = found if found is not None else await simulator_db.insert_simulator(definition)
    environments_db = database_service.get_environments_db()
    version = await environments_db.adopt_deployed(simulator, "prebuilt", simulator_version.database_id, image=image)
    if version.simulator_id != simulator_version.database_id:  # an administrator chose another version
        if version.simulator_id is None:  # a default is ready, so it has one
            raise LookupError(f"the default {version.label} has no simulator")
        chosen = await simulator_db.get_simulator(version.simulator_id)
        if chosen is None:
            raise LookupError(f"{version.label}'s simulator {version.simulator_id} is gone")
        simulator_version = chosen
    return version, simulator_version


DEFAULT = "default"


def parse_version_refs(refs: list[str] | None) -> tuple[bool, dict[str, int | None]]:
    """``environment@number`` / ``environment@default`` references, and the bare ``default`` (every environment at its
    default): whether that was given, and each named environment's number (None: its default). `ValueError` for a
    malformed or repeated one."""
    every, named = False, {}
    for ref in refs or []:
        text = ref.strip()
        if text == DEFAULT:
            every = True
            continue
        environment, at, number = text.rpartition("@")
        if not at or not environment or not (number == DEFAULT or number.isdigit()):
            raise ValueError(f"{ref!r} is not environment@number, environment@default or default")
        if environment in named:
            raise ValueError(f"{environment} is named twice")
        named[environment] = None if number == DEFAULT else int(number)
    return every, named


async def resolve_versions(
    database_service: "DatabaseService", refs: list[str] | None, environments: set[str], *, require_all: bool
) -> dict[str, int]:
    """The version number each of ``environments`` runs at, from ``refs``: a default resolved to its number now.
    With ``require_all``, every environment must be named (or ``default`` given); otherwise one not named is left out
    (its runs get the default when they are recorded). `VersionUnavailableError` for a version runs cannot use, an
    environment the runs do not use, or one missing under ``require_all``; `ValueError` for a malformed reference."""
    every, named = parse_version_refs(refs)
    unused = sorted(set(named) - environments)
    if unused:
        raise VersionUnavailableError(
            f"these runs do not use {', '.join(unused)}; they use {', '.join(sorted(environments))}"
        )
    missing = sorted(environments - set(named))
    if require_all and missing and not every:
        raise VersionUnavailableError(
            f"name a version of {', '.join(missing)} (environment@number, environment@default, or default)"
        )
    resolved: dict[str, int] = {}
    shared = shared_environment()
    for environment in sorted(environments):
        number = named.get(environment)
        if number is not None:
            await chosen_version(database_service, environment, number)
            resolved[environment] = number
        elif environment in named or every:
            version, _ = await version_for(database_service, None if environment == shared else environment)
            resolved[environment] = version.number
    return resolved
