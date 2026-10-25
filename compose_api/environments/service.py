"""Creating environment versions (docs/plan-environment-versions.md, step 4): a shared one from its spec resolved at
a date, a prebuilt one from an image by digest. The routes in ``api/routers/registry.py`` check the administrator
role; this module decides what a request means."""

import datetime
import re

from pbest.utils.input_types import ContainerizationFileRepr

from compose_api.db.database_service import DatabaseService
from compose_api.db.services.environments_db import VersionSource
from compose_api.environments.definition import shared_definition
from compose_api.environments.lock import Lock, LockError, SharedSpec, changes, compile_lock
from compose_api.registry.environments import EnvironmentSpec, load_environments
from compose_api.simulation import builds
from compose_api.simulation.models import EnvironmentVersion, LockPreview, NewEnvironmentVersion, PackageChange
from compose_api.simulation.prebuilt import prebuilt_definition

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
