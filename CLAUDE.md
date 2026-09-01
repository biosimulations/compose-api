# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Dependencies are managed with `uv` (Python >= 3.13.2 locally; CI also runs 3.12). Everything runs through `uv run`.

```bash
make install                 # uv sync + install pre-commit hooks
make run                     # uvicorn compose_api.api.main:app --reload on :8000
make check                   # uv lock --locked, pre-commit (ruff lint+format), mypy --strict, deptry
make test                    # pytest with coverage
make docs                    # mkdocs serve
```

Single test / subset:

```bash
uv run python -m pytest tests/simulation/test_scheduler.py::test_name -s
uv run python -m pytest tests/common -k nats
uv run mypy                  # files/strict config comes from pyproject.toml; do not pass paths
```

Database migrations (alembic, against the configured Postgres):

```bash
make db-migrate msg="add column x"   # autogenerate revision from ORM model changes
make db-upgrade                      # alembic upgrade head
make db-stamp                        # mark existing DB as at head without running migrations
```

Generated API client (checked into `compose_api/api/client/`, excluded from ruff/mypy — never hand-edit):

```bash
python3 compose_api/api/openapi_spec.py   # writes compose_api/api/spec/openapi_3_1_0_generated.yaml
LIB_DIR=<path> make clients               # regenerates client via openapi-python-client
```

Release & deploy: `make tag` (`tag.sh` bumps `pyproject.toml` + `compose_api/version.py`, commits, tags, pushes — the tag push triggers the image build workflow); `kustomize/scripts/build_and_push.sh` builds/pushes `ghcr.io/biosimulations/compose-api`; `make deploy` applies `kustomize/overlays/compose-api-rke`. Publishing a GitHub *release* (separate from the tag push) additionally archives it to Zenodo under concept DOI 10.5281/zenodo.21127421 via the reusable `virtualcell/zenodo-maint` workflow; keep `CITATION.cff` and `.zenodo.json` in step with the authors and version, as a weekly drift check flags mismatches.

## Test environment

- Tests requiring a real SLURM cluster are skipped unless `SLURM_SUBMIT_KEY_PATH` is set:
  `@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, ...)`. Add that marker to any new test that
  submits jobs or SSHes to HPC.
- Postgres, NATS, and MongoDB fixtures use **testcontainers**, so Docker must be running for most of the suite.
- All fixtures live in `tests/fixtures/` and are re-exported from `tests/conftest.py`; add new fixtures there too.
- Service fixtures swap the module-level singletons in `compose_api/dependencies.py` and restore the previous value on
  teardown — follow that save/set/yield/restore pattern.

## Configuration

`compose_api/config.py` defines a single pydantic-settings `Settings`, cached by `get_settings()`. Values load from,
in order: `assets/dev/config/.dev_env` (git-ignored; copy from `.dev_env_TEMPLATE`), then `$CONFIG_ENV_FILE`, then
`$SECRET_ENV_FILE`. Because `get_settings()` is `@lru_cache`d and read at import time in several modules, env changes
require a process restart.

`namespace` (`dev` / `prod` / `test`) is not just a label — it selects the HPC storage subtree
(`{simulation_store_base_path}/{namespace}/...` in `hpc_utils.py`) and selects `TestDataService` over `DataServiceHpc`
in `init_standalone`.

## Architecture

FastAPI service that accepts simulation requests, runs them as Singularity/Apptainer containers on a remote SLURM
cluster over SSH, tracks job state in Postgres, and serves results back. There is no local execution path — HPC is the
only backend.

**Request flow:** router (`compose_api/api/routers/`) → handler (`compose_api/simulation/handlers.py`) →
`SimulationService` (submits to SLURM) + `DatabaseService` (records the run) → `JobMonitor` (updates status) →
`DataService` (fetches `results.zip`).

**Wiring / dependency injection.** `compose_api/dependencies.py` holds module-level singletons
(`global_database_service`, `global_simulation_service`, `global_job_monitor`, `global_data_service`,
`global_postgres_engine`) with `get_*` / `set_*` / `get_required_*` accessors. `init_standalone()` builds them all
during the FastAPI lifespan; `shutdown_standalone()` tears them down. Routers call the plain `get_*` and raise a 500
themselves when the service is `None`. Two consequences worth knowing:
- `dependencies.py` imports `TestDataService` from `tests.fixtures.mocks`, so the `tests` package ships with the app.
- Circular imports are real here: `simulation_service.py` imports `get_required_database_service` *inside* functions,
  and `dependencies.py` imports `SimulationService` mid-file. Keep late imports late.

**Routers** are registered by name from `APP_ROUTERS` in `api/main.py` via `importlib`, and each module must expose a
module-level `config = RouterConfig(router=APIRouter(), prefix=..., dependencies=[])`. Registration failures are logged
and swallowed — an import error in a router silently drops its endpoints rather than failing startup. Prefixes:
`/simulation` (submit), `/results` (status, results file), `/core` (simulator/process/step catalogs), `/curated`
(pre-baked copasi/tellurium runs). Every endpoint sets an explicit `operation_id` because those become the generated
client's method names.

**HPC layer.** `SSHService` (asyncssh: `run_command`, `scp_upload`, `scp_download`) → `SlurmService`
(`sbatch --parsable`, `squeue`, `sacct` parsing into `SlurmJob`) → `SimulationServiceHpc`, which writes sbatch scripts
inline as f-string heredocs in `simulation_service.py` (one for simulation runs, one for `singularity build
--fakeroot` container builds). All remote paths come from `compose_api/simulation/hpc_utils.py` — `sims/`, `images/`,
`htclogs/`, `slurm_sbatch/` under the namespace directory. Never hardcode a remote path; add a helper there.
The container definition is generated by `pbest`, hashed (`get_singularity_hash`, md5 of the def file), and that hash
is the identity of a `SimulatorVersion` — an unseen hash triggers a container build job before the simulation runs.

**Job tracking.** An `HpcRun` row links a SLURM job id, a `correlation_id`, and a `JobType`
(`SIMULATION` / `BUILD_CONTAINER`). `JobMonitor` updates status two ways: a 5-second polling loop reconciling
`squeue`/`sacct` against running `HpcRun` rows, and (only when `hpc_has_messaging` is true) a NATS subscription on
`nats_worker_event_subject` that correlates `WorkerEvent`s by `correlation_id`. Unparseable SLURM states are coerced to
`JobStatus.UNKNOWN` rather than raising. `internal_subscribe(queue, job_id)` lets in-process callers await transitions.

**Persistence.** `DatabaseServiceSQL` (async SQLAlchemy + asyncpg) is a facade over three ORM executors:
`get_simulator_db()`, `get_hpc_db()`, `get_package_db()` (`compose_api/db/services/`, tables in `db/tables/`). Startup
currently calls `create_db()` (`metadata.create_all` + alembic `stamp head`) rather than `upgrade_db()`, so schema
changes still need a matching alembic revision for existing deployments. MongoDB settings and fixtures exist but the
live path is Postgres.

## Companion repositories

This service is one side of a three-package loop. `../pbest` is checked out next to this repo
(github.com/biosimulations/pbest) and has its own CLAUDE.md worth reading before changing anything below.

- **compose-api imports pbest at runtime.** `pbest.utils.input_types` supplies domain types used here directly —
  `ContainerizationFileRepr` (persisted in `db/tables/simulator_tables.py` and carried on `Simulator`),
  `ContainerizationEngine`, `ExperimentPrimaryDependencies`. `handlers.run_simulation` calls
  `generate_container_def_file(_default_registry_deps(), ContainerizationEngine.APPTAINER)`; that def file's md5 is the
  `SimulatorVersion` identity, so **bumping the `pbest==0.6.3` pin changes the hash and triggers a fresh container
  build** on the next run (pbest's release script rewrites the `pbest_tag` baked into the generated def file).
  The pin is exact and resolves from PyPI — the local `../pbest` working copy is *not* what compose-api runs against
  unless you deliberately install it editable, and it can sit on a different version than the pin.
- **pbest calls back over HTTP** using the published `compose-api-client` package (imported as `compose_api_client`,
  currently 0.2.0), generated from this repo's OpenAPI spec, defaulting to `https://compose.cam.uchc.edu`. It uses
  `run-simulation`, `get-simulations-status-batch`, `get-simulation-status`, and `get-simulation-results-file`; those
  `operation_id`s *are* pbest's function names, so renaming one is a breaking change downstream. pbest's
  `_normalize_pbg_paths` is what packs a local process-bigraph document into the `experiment.omex` that arrives at
  `/simulation/run`, and its batch path submits with `batch_submission=True` then polls the batch status endpoint —
  which is why the batch branch in the sbatch template uses the smaller batch partition/QoS and 1 CPU / 1 GB.
- **Changing a request or response model is a four-step release**: regenerate the spec and client here, publish
  `compose-api-client`, bump it in pbest, then bump the `pbest` pin here. Note `make clients` writes to two
  destinations — the in-repo `compose_api/api/client/` and `$LIB_DIR` (the separate compose-api-client repo, not in
  this workspace) — and the published package additionally carries a hand-written `utils/run_simulation_and_wait.py`
  that the generator does not produce and must not clobber.
- The production host is `compose.cam.uchc.edu` in all three places that must agree: the RKE ingress
  (`kustomize/overlays/compose-api-rke/ingress.yaml`), `ServerMode.PROD` plus `APP_ORIGINS` here, and pbest's default
  client base URL. Changing it means changing all three.

## Conventions

- ruff, line length 120, with a broad rule set (bandit `S`, bugbear `B`, tryceratops `TRY`, …); `make check` must be
  clean. `alembic/`, `documentation/`, and `compose_api/api/client/` are excluded.
- mypy runs `--strict` over `compose_api` and `tests`; use `typing_extensions.override` on interface implementations,
  as the existing services do.
- Domain models are pydantic (`compose_api/simulation/models.py` subclasses a local `BaseModel` that adds
  `as_payload()`); enums are `StrEnum` when their string value is wire- or path-visible.
