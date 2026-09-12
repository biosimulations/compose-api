import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

KV_DRIVER = Literal["file", "s3", "gcs"]
TS_DRIVER = Literal["zarr", "n5", "zarr3"]

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
    slurm_qos: str = ""
    batch_slurm_qos: str = ""
    batch_slurm_partition: str = ""

    simulation_store_base_path: str = ""
    hpc_sim_config_file: str = "publish.json"
    hpc_has_messaging: bool = False

    nats_url: str = ""
    nats_worker_event_subject: str = "worker.events"

    nats_emitter_url: str = ""
    nats_emitter_magic_word: str = "emitter-magic-word"

    dev_mode: str = "0"
    app_dir: str = f"{REPO_ROOT}/app"
    assets_dir: str = f"{REPO_ROOT}/assets"
    marimo_api_server: str = ""

    # Should mount to /projects/CRBM/compose_api externally
    internal_mount_dir: str = "/mnt/projects/CRBM/compose_api"
    namespace: str = "test"
    containers_output_dir: str = "/experiment/output"
    container_service: str = "APPTAINER"

    # Repository holding the prebuilt simulator images, without a tag; the tag is the
    # SimulatorVersion's container_def_hash. This was hardcoded to a personal Docker Hub
    # account belonging to someone who has since left, which is why it is configuration
    # now. No image is published at the default yet: until one is, every run takes the
    # build fallback in handlers._download_or_build_container, which is the intended
    # behaviour when a download fails, not an error.
    simulator_image_repository: str = "ghcr.io/biosimulations/registry_env"


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
