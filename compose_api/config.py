import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings

KV_DRIVER = Literal["file", "s3", "gcs"]
TS_DRIVER = Literal["zarr", "n5", "zarr3"]

# Every verified caller holds DEFAULT_ROLE (compose_api/authentication.py, which re-exports it); an anonymous caller
# has no principal and so no role. It is the tenant-wide Auth0 role "user" owned by auth0-pulumi/biosim-platform
# (roles.py: biosim_user_role) -- keep the spelling in step. Defined here so Settings can refuse it as admin_role.
DEFAULT_ROLE = "user"

# -- load dev env -- #
REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
DEV_ENV_PATH = os.path.join(REPO_ROOT, "assets", "dev", "config", ".dev_env")
load_dotenv(DEV_ENV_PATH)  # NOTE: create an env config at this filepath if dev

ENV_CONFIG_ENV_FILE = "CONFIG_ENV_FILE"
ENV_SECRET_ENV_FILE = "SECRET_ENV_FILE"  # noqa: S105 Possible hardcoded password assigned to: "ENV_SECRET_ENV_FILE"

if os.getenv(ENV_CONFIG_ENV_FILE) is not None and os.path.exists(str(os.getenv(ENV_CONFIG_ENV_FILE))):
    load_dotenv(os.getenv(ENV_CONFIG_ENV_FILE))

if os.getenv(ENV_SECRET_ENV_FILE) is not None and os.path.exists(str(os.getenv(ENV_SECRET_ENV_FILE))):
    load_dotenv(os.getenv(ENV_SECRET_ENV_FILE))


class Settings(BaseSettings):
    storage_bucket: str = "files.biosimulations.dev"
    storage_endpoint_url: str = "https://storage.googleapis.com"
    storage_region: str = "us-east4"
    storage_tensorstore_driver: TS_DRIVER = "zarr3"
    storage_tensorstore_kvstore_driver: KV_DRIVER = "gcs"

    temporal_service_url: str = "localhost:7233"

    storage_local_cache_dir: str = "./local_cache"

    storage_gcs_credentials_file: str = ""

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "biosimulations"
    mongodb_collection_omex: str = "BiosimOmex"
    mongodb_collection_sims: str = "BiosimSims"
    mongodb_collection_compare: str = "BiosimCompare"

    postgres_user: str = "<USER>"
    postgres_password: str = ""
    postgres_database: str = "compose_api"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_pool_size: int = 10  # number of connections in the pool
    postgres_max_overflow: int = 5  # maximum number of connections that can be created beyond the pool size
    postgres_pool_timeout: int = 30  # timeout for acquiring a connection from the pool in seconds
    postgres_pool_recycle: int = 1800  # recycle connections every seconds

    slurm_submit_host: str = ""
    slurm_submit_port: int = 22
    slurm_submit_user: str = ""
    slurm_submit_key_path: str = ""
    slurm_submit_known_hosts: str | None = None
    slurm_partition: str = ""
    slurm_node_list: str = ""  # comma-separated list of nodes, e.g., "node1,node2"
    slurm_build_node: str = ""
    # Where containers are built (compose_api/simulation/build_k8s.py): "slurm" (a fakeroot build on
    # slurm_build_node) or "k8s" (a Kubernetes Job in build_k8s_namespace, the image placed on the shared filesystem
    # through build_k8s_pvc_claim, mounted at build_k8s_pvc_mount_path: the path the SLURM nodes read it at).
    build_backend: str = "slurm"
    build_k8s_namespace: str = ""
    build_k8s_image: str = "ghcr.io/apptainer/apptainer:1.3.6"
    build_k8s_pvc_claim: str = ""
    build_k8s_pvc_mount_path: str = ""
    build_k8s_pvc_sub_path: str = ""
    build_k8s_run_as_uid: int = 0
    build_k8s_run_as_gid: int = 0
    build_k8s_supplemental_groups: str = ""
    build_k8s_timeout_seconds: int = 7200
    slurm_qos: str = ""
    batch_slurm_qos: str = ""
    batch_slurm_partition: str = ""

    simulation_store_base_path: str = ""
    hpc_sim_config_file: str = "publish.json"

    dev_mode: str = "0"
    app_dir: str = f"{REPO_ROOT}/app"
    assets_dir: str = f"{REPO_ROOT}/assets"
    marimo_api_server: str = ""

    # Should mount to /projects/CRBM/compose_api externally
    internal_mount_dir: str = "/mnt/projects/CRBM/compose_api"
    namespace: str = "test"
    containers_output_dir: str = "/experiment/output"
    # The Python of the separate environment process-bigraph-lang is installed in (sedml/pblang-requirements.txt):
    # it needs bigraph-schema 1.6, this service's environment has pbest's 1.0, so SED-ML translation runs its CLI there
    # (docs/plan-sedml.md, phase 3). `make pblang` makes .pblang/ in a checkout; the API image builds the same at /app.
    pblang_python: str = f"{REPO_ROOT}/.pblang/bin/python"
    # Archives fetched from BioModels and biosimulations.org (sedml/sources.py), by id and upstream revision.
    sources_cache_dir: str = f"{REPO_ROOT}/scratch/sources"
    container_service: str = "APPTAINER"

    # Repository holding the prebuilt simulator images, without a tag; the tag is the
    # SimulatorVersion's container_def_hash. This was hardcoded to a personal Docker Hub
    # account belonging to someone who has since left, which is why it is configuration
    # now. No image is published at the default yet: until one is, every run takes the
    # build fallback in handlers._download_or_build_container, which is the intended
    # behaviour when a download fails, not an error.
    simulator_image_repository: str = "ghcr.io/biosimulations/registry_env"

    # What /simulation/run does with a process address the registry manifest does not allow
    # (compose_api/registry/manifest.yaml). "enforce" rejects the submission with a 400; "warn" logs and runs it,
    # as an escape hatch if enforcement turns out to block a real user. Unsafe addresses -- non-local protocols
    # and the arbitrary-import `local:!` form -- are rejected under either policy.
    address_policy: Literal["enforce", "warn"] = "enforce"

    # Submission supervision (#238). The task submitting a simulation (fetching or building its container, then
    # sbatch) heartbeats on the simulation; the job monitor fails one whose heartbeat is older than
    # submission_stale_seconds, since its task is gone (an API restart). A task running longer than
    # submission_timeout_seconds is cancelled and fails the simulation; a first container build can take an hour.
    submission_stale_seconds: int = 300
    submission_timeout_seconds: int = 4 * 3600
    # The durable submission queue (docs/plan-durable-submission.md). A run is staged and recorded as `requested`;
    # the submission worker leases due rows (a lost worker's lease expires and another resumes the row), retries a
    # transient failure with backoff up to submission_max_attempts, and works on up to submission_worker_concurrency
    # rows at once. Where the store is not mounted (development, tests), files are staged in submission_staging_dir.
    submission_lease_seconds: int = 120
    submission_max_attempts: int = 6
    submission_worker_concurrency: int = 8
    submission_poll_seconds: float = 5.0
    submission_staging_dir: str = os.path.join(tempfile.gettempdir(), "compose-api-staging")
    # How often the API checks every simulator's SIF against the store and adopts unrecorded ones
    # (compose_api/simulation/images.py); the first pass runs at startup.
    image_verify_interval_seconds: int = 3600

    # Simulators published by their owners as OCI images, by name: a request's `simulator`
    # query parameter selects one and the job runs in that image instead of the shared one
    # (compose_api/simulation/prebuilt.py). Only these names are accepted, so a request can
    # never pull an arbitrary image. Pin by digest or an immutable tag: the cached SIF is
    # keyed on the reference. In the environment, a JSON object:
    #   PREBUILT_SIMULATORS='{"viva-pde-particle": "ghcr.io/vivarium-collective/viva-pde-particle-compose:sha-abc1234"}'
    prebuilt_simulators: dict[str, str] = {}

    # Auth0 access-token verification (compose_api/authentication.py). Neither is a secret. While either is
    # empty no token can be verified: anonymous requests still work and any supplied bearer token gets a 401.
    auth0_domain: str = ""  # e.g. dev-bu7yo7484tyxu6a1.us.auth0.com -- no scheme, no trailing slash
    auth0_audience: str = ""  # the Auth0 API Identifier, exactly as shown in the dashboard
    # The web UI's Auth0 Single Page Application (compose_api/api/webapp.py). Not a secret: an SPA has none. The UI
    # offers login only when this and both values above are set; it must be allowed to request auth0_audience.
    auth0_spa_client_id: str = ""
    # Role name granting read access to every private simulation (compose_api/authorization.py). Empty disables
    # the admin bypass so the tenant-wide `admin` role does not automatically read private compose-api simulations.
    # DEFAULT_ROLE is refused: every signed-in caller holds it, so it would let anyone read every private simulation.
    admin_role: str = ""

    # The static web UI build served at /ui (webapp/, `npm run generate`). Absent: the API runs without a UI.
    webapp_dist_dir: str = f"{REPO_ROOT}/webapp/.output/public"
    # Enforce the UI's Content-Security-Policy (compose_api/api/webapp.py) instead of only reporting violations to
    # /webapp/csp-report. Turn on once the reports show the policy matches what the UI loads.
    webapp_csp_enforce: bool = False

    @field_validator("admin_role")
    @classmethod
    def _admin_role_is_not_everyone(cls, value: str) -> str:
        # Fails the deployment at startup (settings load at import) rather than serving private simulations to all.
        if value.strip() == DEFAULT_ROLE:
            raise ValueError(
                f"ADMIN_ROLE must not be {DEFAULT_ROLE!r}: every signed-in caller holds that role, so it would let"
                " anyone who signs in read every private simulation. Name a role only administrators hold, or leave"
                " it empty"
            )
        return value


@lru_cache
def _load_settings() -> Settings:
    """Load settings from the environment once. Never call directly; use get_settings()."""
    return Settings()


# Active override layers, innermost last. Each layer is owned by exactly one caller
# (normally a test fixture) and is removed by identity, so teardown order does not
# matter and two callers overriding disjoint fields compose. Whole-object replacement
# would not: it cannot tell a disjoint override from a conflicting one.
_settings_layers: list[dict[str, Any]] = []


def get_settings() -> Settings:
    """Return the effective settings.

    With no override active this is the cached environment-derived object. With layers
    active it is a fresh copy on every call, so a caller that captured a Settings earlier
    keeps the older view -- resolve settings at use, not at construction.
    """
    if not _settings_layers:
        return _load_settings()
    merged: dict[str, Any] = {}
    for layer in _settings_layers:
        merged.update(layer)
    return _load_settings().model_copy(update=merged)


@contextmanager
def override_settings(**fields: Any) -> Iterator[Settings]:
    """Temporarily override individual settings fields.

    Raises if a field is already overridden by another active layer, so contention
    surfaces at setup instead of resolving silently to whichever caller ran last.
    """
    unknown = fields.keys() - type(_load_settings()).model_fields.keys()
    if unknown:
        raise KeyError(f"unknown settings field(s): {sorted(unknown)}")
    clashes = {key for layer in _settings_layers for key in layer} & fields.keys()
    if clashes:
        raise RuntimeError(f"settings already overridden by an active layer: {sorted(clashes)}")
    layer = dict(fields)
    _settings_layers.append(layer)
    try:
        yield get_settings()
    finally:
        _settings_layers.remove(layer)


def get_local_cache_dir() -> Path:
    settings = get_settings()
    local_cache_dir = Path(settings.storage_local_cache_dir)
    local_cache_dir.mkdir(parents=True, exist_ok=True)
    return local_cache_dir
