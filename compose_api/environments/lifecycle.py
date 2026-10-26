"""A composed version's life after it is created: locked, built, read back, its compliance cases started; and a
mash-up made for a run that no environment covers (docs/plan-environment-composition.md, steps 4, 5b and 7b).

The administrator's routes (``api/routers/registry.py``) and the run route (``api/routers/simulation.py``) both use
these. The services are looked up through ``compose_api.dependencies`` when called, as the routes' own are.
"""

import datetime
import hashlib
import logging
import random
import string

from compose_api import dependencies
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseService
from compose_api.environments import compliance_runs
from compose_api.environments import service as environment_service
from compose_api.environments.contents import inspect_prebuilt_version, inspect_shared_version, record_contents
from compose_api.registry.environments import EnvironmentSpec, load_environments
from compose_api.registry.manifest import HPC_MINIMUM_LEVEL, Manifest
from compose_api.simulation import handlers
from compose_api.simulation.models import EnvironmentVersion, NewEnvironmentVersion, SimulatorVersion, VersionState

logger = logging.getLogger(__name__)

#: at most this many mash-ups are locked or built at once (D7.5); more wait for one to finish
MAX_MASH_UP_BUILDS = 2
#: their versions in these states count against that
_UNDER_WAY = frozenset({VersionState.RESOLVING, VersionState.BUILDING})


def _suffix() -> str:
    return "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 a name, not a secret


async def build_version(version: EnvironmentVersion, simulator: SimulatorVersion) -> None:
    """Make the version's image available through the run path's own function; its state follows the outcome."""
    database_service = dependencies.get_required_database_service()
    environments_db = database_service.get_environments_db()
    try:
        await handlers.ensure_image(
            simulator,
            database_service=database_service,
            simulation_service_slurm=dependencies.get_required_simulation_service(),
            job_monitor=dependencies.get_required_job_monitor(),
            random_string=_suffix(),
        )
    except Exception:
        logger.exception(f"The image of {version.label} (simulator {simulator.database_id}) failed")
        await environments_db.set_state(version.database_id, VersionState.FAILED)
        return
    await environments_db.set_state(version.database_id, VersionState.READY)
    logger.info(f"{version.label} is ready")
    await read_back(version)
    await start_compliance(version)


async def start_compliance(version: EnvironmentVersion) -> None:
    """Run the cases of a composed version's entries in it (step 5b). Never fails the version: an entry whose cases did
    not run stays untested there."""
    try:
        await compliance_runs.start(dependencies.get_required_database_service(), version)
    except Exception:
        logger.exception(f"The compliance cases of {version.label} could not be started")


async def resolve_and_build(version: EnvironmentVersion) -> None:
    """Lock a composed version, then build its image as any version's (``build_version``)."""
    database_service = dependencies.get_required_database_service()
    suffix = _suffix()
    try:
        resolved = await environment_service.resolve_composed(database_service, version, suffix)
    except Exception:
        logger.exception(f"Resolving {version.label} failed")
        await database_service.get_environments_db().set_failure(
            version.database_id, "resolving failed unexpectedly; see the service log"
        )
        return
    if resolved is None:
        logger.info(f"{version.label} did not resolve")
        return
    await build_and_export(*resolved, suffix=suffix)


async def build_and_export(version: EnvironmentVersion, simulator: SimulatorVersion, suffix: str | None = None) -> None:
    """Build a resolved version, then offer its uv form if it has one."""
    await build_version(version, simulator)
    if await environment_service.export_uv(dependencies.get_required_database_service(), version, suffix or _suffix()):
        logger.info(f"{version.label} has a uv form")


async def read_back(version: EnvironmentVersion, reread: bool = False) -> None:
    """Store what the version's image installed and provides: left beside a built image by its build (or, with
    ``reread``, by a Job that reads the built image again), or read from a pulled (prebuilt) one by a Job of its own.
    Never fails the version."""
    database_service = dependencies.get_required_database_service()
    k8s = get_settings().build_backend == "k8s"
    try:
        if version.image is not None:
            recorded = k8s and await inspect_prebuilt_version(database_service, version)
        elif reread:
            recorded = k8s and await inspect_shared_version(database_service, version)
        else:
            recorded = await record_contents(database_service, version)
    except Exception:
        logger.exception(f"Reading back {version.label} failed")
        return
    if not recorded:
        logger.info(f"Nothing was read back from {version.label}'s image")


# --- mash-ups (step 7b; D7.4 to D7.7) --------------------------------------------------------------------------------


class MashUpError(Exception):
    """A mash-up cannot be made or used for this run: why, and the HTTP status that says so."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def mash_up_name(entries: set[str]) -> str:
    """``mash-<10 hex>``: the identity of a mash-up is its set of entries (D7.6)."""
    return "mash-" + hashlib.sha256(",".join(sorted(entries)).encode()).hexdigest()[:10]


def composable(entries: set[str], manifest: Manifest) -> list[str]:
    """Why these entries cannot be composed into a mash-up (empty when they can): each must say how it installs, and a
    component must be `tested` (D7.4). A library's level gates nothing, as in a declared environment (libvcell is
    `listed` in registry_env): what runs is a component's classes."""
    by_id = {e.id: e for e in manifest.entries}
    problems = []
    for entry_id in sorted(entries):
        entry = by_id.get(entry_id)
        if entry is None:
            problems.append(f"no registry entry {entry_id!r}")
        elif entry.install is None and not entry.conda:
            problems.append(f"`{entry_id}` cannot be composed yet: it does not say how it installs")
        elif entry.kind == "component" and not entry.level.at_least(HPC_MINIMUM_LEVEL):
            problems.append(f"`{entry_id}` is at level `{entry.level}`; a mash-up needs `{HPC_MINIMUM_LEVEL}`")
    return problems


def _mash_up_spec(name: str, entries: set[str]) -> EnvironmentSpec:
    """A mash-up as a composition: its entries, on the shared environment's Python."""
    shared = next(e for e in load_environments().environments if e.kind == "shared")
    return EnvironmentSpec(
        name=name, kind="mash-up", python=shared.python, entries=sorted(entries), python_version=shared.python_version
    )


async def mash_up_specs(database_service: DatabaseService) -> list[EnvironmentSpec]:
    """The mash-ups a run may use: those whose default version is ready or building (D7.3), as compositions."""
    environments_db = database_service.get_environments_db()
    specs = []
    for record in await environments_db.environments():
        if record.kind != "mash-up" or not record.entries:
            continue
        default = await environments_db.get_default(record.name)
        if default is not None and default.state in (VersionState.READY, VersionState.BUILDING):
            specs.append(_mash_up_spec(record.name, set(record.entries)))
    return specs


async def mash_up_spec(database_service: DatabaseService, name: str) -> EnvironmentSpec | None:
    """A mash-up the database holds, as a composition (an administrator makes its later versions, D7.7)."""
    records = await database_service.get_environments_db().environments()
    record = next((r for r in records if r.name == name and r.kind == "mash-up" and r.entries), None)
    return _mash_up_spec(record.name, set(record.entries or [])) if record is not None else None


async def _builds_under_way(database_service: DatabaseService) -> int:
    environments_db = database_service.get_environments_db()
    count = 0
    for record in await environments_db.environments():
        if record.kind == "mash-up":
            versions = await environments_db.list_versions(record.name)
            count += sum(1 for v in versions if v.state in _UNDER_WAY)
    return count


async def mash_up_for(
    database_service: DatabaseService, entries: set[str], created_by: str
) -> tuple[EnvironmentVersion, SimulatorVersion | None]:
    """The version of the mash-up of exactly ``entries`` a run uses, made if it does not exist yet (D7.4): locked here,
    while the request waits, so a conflict is a 409 with pixi's explanation; its build is the caller's to start (the
    simulator returned, None when it is already under way or done). `MashUpError` when it cannot be made or used."""
    name = mash_up_name(entries)
    environments_db = database_service.get_environments_db()
    # only a mash-up's first version is made for a run (D7.7): once it exists, runs use it or are told why they cannot
    existing = await environments_db.get_default(name) or next(iter(await environments_db.list_versions(name)), None)
    if existing is not None:
        if existing.state in (VersionState.FAILED, VersionState.RETIRED):
            raise MashUpError(
                409,
                f"{existing.label} is {existing.state}: {existing.failure or 'see its page'}. An administrator"
                " can make a new version of it",
            )
        return existing, None  # the same set is never built twice (D7.5)
    if await _builds_under_way(database_service) >= MAX_MASH_UP_BUILDS:
        raise MashUpError(429, f"{MAX_MASH_UP_BUILDS} environments are being made already; try again shortly")
    await environments_db.ensure_mash_up(name, sorted(entries))
    request = NewEnvironmentVersion(
        resolved_at=datetime.datetime.now(datetime.UTC), note=f"made for a run that needed {', '.join(sorted(entries))}"
    )
    try:
        version = await environment_service.create_composed(
            database_service, _mash_up_spec(name, entries), request, created_by, bundled=False
        )
    except environment_service.VersionRequestError as e:
        raise MashUpError(409, str(e)) from e
    resolved = await environment_service.resolve_composed(database_service, version, _suffix())
    if resolved is None:
        failed = await environments_db.get_version(version.database_id)
        raise MashUpError(409, (failed.failure if failed else None) or f"{version.label} did not resolve")
    built, simulator = resolved
    await environments_db.set_default(name, built.database_id)  # its first version runs while it builds (RUNNABLE)
    logger.info(f"{built.label} made for a run by {created_by}: {', '.join(sorted(entries))}")
    return built, simulator
