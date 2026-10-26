"""Creating environment versions (docs/plan-environment-versions.md, step 4): a shared one from its spec resolved at
a date, a prebuilt one from an image by digest. The routes in ``api/routers/registry.py`` check the administrator
role; this module decides what a request means."""

import datetime
import logging
import re

from pbest.utils.input_types import ContainerizationFileRepr

from compose_api.db.database_service import DatabaseService
from compose_api.db.services.environments_db import VersionSource
from compose_api.environments import pixi, uv_export
from compose_api.environments.definition import shared_definition
from compose_api.environments.lock import Lock, LockError, SharedSpec, changes, compile_lock
from compose_api.registry.environments import EnvironmentSpec, load_environments, spec_problems
from compose_api.registry.manifest import load_manifest
from compose_api.simulation import builds
from compose_api.simulation.models import (
    EnvironmentExport,
    EnvironmentVersion,
    EnvironmentVersionDetail,
    LockPreview,
    NewEnvironmentVersion,
    PackageChange,
    SimulatorVersion,
    VersionState,
)
from compose_api.simulation.prebuilt import prebuilt_definition

logger = logging.getLogger(__name__)

_DIGEST = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


class VersionRequestError(ValueError):
    """The request cannot make a version of this environment (a 422)."""


def environment_spec(name: str) -> EnvironmentSpec | None:
    """An environment the service knows (``environments.yaml``), whether or not this deployment pins an image."""
    return next((e for e in load_environments().environments if e.name == name), None)


def _shared(request: NewEnvironmentVersion) -> tuple[SharedSpec, str]:
    if request.image is not None:
        raise VersionRequestError("a shared environment is made from libraries, not an image")
    registry = SharedSpec.from_registry()
    if request.libraries is None or request.libraries == registry.libraries:
        return registry, "registry"
    for lib in request.libraries:
        if not lib.get("name") or lib.get("package_registry") not in ("pypi", "conda-forge"):
            raise VersionRequestError(f"each library needs a name and a package_registry (pypi, conda-forge): {lib}")
    return SharedSpec(libraries=request.libraries, pbest=registry.pbest), "custom"


async def _lock(spec: SharedSpec, resolved_at: datetime.datetime | None) -> Lock:
    try:
        return await compile_lock(spec, resolved_at or datetime.datetime.now(datetime.UTC))
    except LockError as e:
        raise VersionRequestError(f"the spec does not resolve: {e}") from e


async def preview(
    database_service: DatabaseService, environment: EnvironmentSpec, request: NewEnvironmentVersion
) -> LockPreview:
    """What a shared version made from ``request`` would be, and how its lock differs from the default's."""
    if is_composed(environment):
        raise VersionRequestError(
            f"{environment.name} is composed: its lock is resolved in a Job, in the background. Create a version, and"
            " compare it with another once it has resolved"
        )
    if environment.kind != "shared":
        raise VersionRequestError(f"{environment.name} is prebuilt: its versions are images, with no lock")
    spec, origin = _shared(request)
    lock = await _lock(spec, request.resolved_at)
    environments_db = database_service.get_environments_db()
    existing = await environments_db.find_by_lock(environment.name, lock.sha256)
    default = await environments_db.get_default_detail(environment.name)
    # A version made before locks is compared by what its image installed (read back from it)
    basis = (default.lock or default.installed) if default is not None else None
    return LockPreview(
        environment=environment.name,
        resolved_at=lock.resolved_at,
        origin=origin,
        lock_sha256=lock.sha256,
        lock=lock.text,
        existing=existing.number if existing is not None else None,
        against=default.number if default is not None and basis else None,
        against_basis=("lock" if default.lock else "installed") if default is not None and basis else None,
        changes=[
            PackageChange(name=name, before=before, after=after)
            for name, before, after in (changes(basis, lock.text) if basis else [])
        ],
    )


async def create(
    database_service: DatabaseService,
    environment: EnvironmentSpec,
    request: NewEnvironmentVersion,
    created_by: str | None,
) -> tuple[EnvironmentVersion, bool]:
    """The version ``request`` describes: new and `building` (True), or the existing one with the same definition.
    Its image is not started here."""
    definition: ContainerizationFileRepr
    if is_composed(environment):
        raise VersionRequestError(f"{environment.name} is composed: its versions are made by create_composed")
    if environment.kind == "shared":
        spec, origin = _shared(request)
        lock = await _lock(spec, request.resolved_at)
        definition = shared_definition(spec, lock)
        source = VersionSource(
            spec=spec.as_json(),
            origin=origin,
            resolved_at=lock.resolved_at,
            lock=lock.text,
            lock_sha256=lock.sha256,
            created_by=created_by,
            note=request.note,
        )
    else:
        if request.libraries is not None or request.resolved_at is not None:
            raise VersionRequestError(f"{environment.name} is prebuilt: a version is an image, given by digest")
        if request.image is None or not _DIGEST.match(request.image):
            raise VersionRequestError("a prebuilt version needs its image by digest: <repository>@sha256:<64 hex>")
        definition = prebuilt_definition(request.image)
        source = VersionSource(image=request.image, created_by=created_by, note=request.note)
    simulator = await builds.simulator_for(database_service.get_simulator_db(), definition)
    return await database_service.get_environments_db().create_version(
        environment.name, environment.kind, simulator.database_id, source
    )


def is_composed(environment: EnvironmentSpec) -> bool:
    """Whether the environment is composed from registry entries (docs/plan-environment-composition.md): its versions
    are pixi locks, resolved in the background, run by compose-api's runner."""
    return bool(environment.entries)


async def create_composed(
    database_service: DatabaseService,
    environment: EnvironmentSpec,
    request: NewEnvironmentVersion,
    created_by: str | None,
) -> EnvironmentVersion:
    """A new composed version, `resolving`: the environment's entries composed at a date. Nothing is locked here
    (``resolve_composed`` does, in the background); the request is checked."""
    if request.image is not None or request.libraries is not None:
        raise VersionRequestError(f"{environment.name} is composed from its registry entries: give a date, not those")
    composition = load_environments().composition
    if composition is None:
        raise VersionRequestError("this service has no composition settings (environments.yaml, `composition`)")
    manifest = load_manifest()
    problems = spec_problems(environment, manifest)
    if problems:
        raise VersionRequestError("; ".join(problems))
    resolved_at = request.resolved_at or datetime.datetime.now(datetime.UTC)
    spec = pixi.ComposedSpec.of(environment, manifest, composition, resolved_at)
    recorded = {
        **spec.as_json(),
        "pixi_toml": pixi.pixi_toml(spec),
        "pixi_image": composition.pixi_image,
        "runner": pixi.runner_source(),  # what it is built and rebuilt with, whatever compose-api's runner becomes
    }
    source = VersionSource(
        spec=recorded,
        origin="registry",
        resolved_at=spec.resolved_at.replace(tzinfo=None),  # stored as naive UTC, as a shared version's is
        created_by=created_by,
        note=request.note,
        runtime_contract=pixi.RUNTIME_CONTRACT,
    )
    return await database_service.get_environments_db().create_resolving(environment.name, environment.kind, source)


async def resolve_composed(
    database_service: DatabaseService, version: EnvironmentVersion, suffix: str
) -> tuple[EnvironmentVersion, SimulatorVersion] | None:
    """Lock a resolving version in its Job, then give it its definition's simulator: the version, now `building`, and
    the simulator to build; None when it failed (it is `failed`, with pixi's explanation or the version it repeats)."""
    from compose_api.simulation.build_k8s import LockFailedError, lock_composed

    environments_db = database_service.get_environments_db()
    recorded = version.spec or {}
    try:
        text = await lock_composed(recorded["pixi_toml"], recorded["pixi_image"], suffix)
    except LockFailedError as e:
        await environments_db.set_failure(version.database_id, f"its entries do not resolve together:\n{e}")
        return None
    except Exception as e:
        logger.exception(f"Locking {version.label} failed")
        await environments_db.set_failure(version.database_id, f"locking failed: {type(e).__name__}: {e}")
        return None
    lock = pixi.PixiLock(text)
    # a version is its lock: a later date that resolves to the same lock is the same version (its workspace differs
    # only in its date, so its definition would not show it)
    same = await environments_db.find_by_lock(version.environment, lock.sha256)
    if same is not None and same.database_id != version.database_id:
        await environments_db.set_failure(version.database_id, f"it resolves to the same lock as {same.label}")
        return None
    types = list(recorded.get("types", []))
    runner = str(recorded.get("runner") or pixi.runner_source())
    definition = pixi.definition_of(recorded["pixi_toml"], types, lock, recorded["pixi_image"], runner)
    simulator = await builds.simulator_for(database_service.get_simulator_db(), definition)
    repeated = await environments_db.set_resolved(version.database_id, simulator.database_id, lock.text, lock.sha256)
    if repeated is not None:
        await environments_db.set_failure(version.database_id, f"it resolves to the same lock as {repeated.label}")
        return None
    resolved = version.model_copy(
        update={"state": VersionState.BUILDING, "simulator_id": simulator.database_id, "lock_sha256": lock.sha256}
    )
    return resolved, simulator


EXPORT_FORMATS = ("pixi", "uv", "requirements")


def export(
    version: EnvironmentVersionDetail, export_format: str | None, exports: dict[str, dict[str, str]] | None = None
) -> EnvironmentExport:
    """The files that recreate ``version`` locally: a composed version's pixi workspace and lock, or its uv project and
    lock (when it needs no conda, step 4b), or a shared one's uv lock as requirements. `VersionRequestError` when it
    has none in that format (a prebuilt image, an older version built before locks, one still resolving, or a uv form
    that needs conda)."""
    composed = version.runtime_contract == pixi.RUNTIME_CONTRACT
    chosen = export_format or ("pixi" if composed else "requirements")
    if chosen not in EXPORT_FORMATS:
        raise VersionRequestError(f"no export format {chosen!r}: one of {', '.join(EXPORT_FORMATS)}")
    if version.lock is None:
        raise VersionRequestError(f"{version.label} has no lock to export: it is {version.state}, or an image")
    if chosen == "uv" and composed:
        made = (exports or {}).get("uv")
        if made is None:
            why = (
                "it needs packages from conda-forge, which uv cannot install"
                if uv_export.needs_conda(version.spec or {})
                else "its uv form has not been made (it is made once the version resolves)"
            )
            raise VersionRequestError(f"{version.label} has no uv form: {why}")
        files = dict(made)
    elif chosen == "pixi" and composed:
        files = {"pixi.toml": str((version.spec or {}).get("pixi_toml", "")), "pixi.lock": version.lock}
    elif chosen == "requirements" and not composed:
        files = {"requirements.txt": version.lock}
    else:
        available = "pixi or uv" if composed else "requirements"
        raise VersionRequestError(f"{version.label} exports as {available}, not {chosen}")
    return EnvironmentExport(environment=version.environment, number=version.number, format=chosen, files=files)


async def export_uv(database_service: DatabaseService, version: EnvironmentVersion, suffix: str) -> bool:
    """Make and keep a resolved composed version's uv form (step 4b), if its entries need nothing from conda-forge:
    a uv project constrained to exactly what pixi locked, locked by uv in a Job, kept only if uv arrived at the same
    packages at the same versions. Whether it was kept; never fails the version."""
    from compose_api.simulation.build_k8s import uv_lock

    spec = version.spec or {}
    environments_db = database_service.get_environments_db()
    detail = await environments_db.get_by_number(version.environment, version.number)
    if detail is None or detail.lock is None or uv_export.needs_conda(spec):
        return False
    pins = uv_export.pypi_pins(detail.lock)
    project = uv_export.pyproject(version.environment, version.number, spec, pins)
    try:
        locked = await uv_lock(project, str(spec["pixi_image"]), suffix)
    except Exception:
        logger.exception(f"The uv form of {version.label} could not be locked")
        return False
    differences = uv_export.differences(pins, uv_export.uv_pins(locked))
    if differences:
        logger.warning(f"The uv form of {version.label} differs from its pixi lock, so it is not kept: {differences}")
        return False
    await environments_db.set_export(version.database_id, "uv", {"pyproject.toml": project, "uv.lock": locked})
    return True


async def build_files(database_service: DatabaseService, simulator_id: int) -> dict[str, str] | None:
    """The files a composed version's definition copies in (``pixi.composed_files``), for the simulator its build is
    of; None for any other simulator (its definition is self-contained)."""
    environments_db = database_service.get_environments_db()
    version = await environments_db.of_simulator(simulator_id)
    if version is None or version.runtime_contract != pixi.RUNTIME_CONTRACT:
        return None
    detail = await environments_db.get_by_number(version.environment, version.number)
    if detail is None or detail.lock is None:
        return None
    recorded = detail.spec or {}
    runner = str(recorded.get("runner") or pixi.runner_source())
    return pixi.composed_files(str(recorded.get("pixi_toml", "")), pixi.PixiLock(detail.lock), runner)
