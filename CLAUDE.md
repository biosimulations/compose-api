# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Dependencies are managed with `uv` (`requires-python` floor 3.13.2; the local runtime is 3.14 and CI runs both 3.13 and 3.14). Everything runs through `uv run`.

```bash
make install                 # uv sync + install pre-commit hooks
make run                     # uvicorn compose_api.api.main:app --reload on :8000
make check                   # uv lock --locked, pre-commit (ruff lint+format), mypy --strict, deptry
                             # `git add` new files FIRST: pre-commit only sees tracked files,
                             # so an untracked file passes here and fails in CI
make test                    # pytest with coverage
make docs                    # mkdocs serve
```

Single test / subset:

```bash
uv run python -m pytest tests/simulation/test_scheduler.py::test_name -s
uv run mypy                  # files/strict config comes from pyproject.toml; do not pass paths
```

Database migrations (alembic, against the configured Postgres):

```bash
make db-migrate msg="add column x"   # autogenerate revision from ORM model changes
make db-upgrade                      # alembic upgrade head
make db-stamp                        # mark existing DB as at head without running migrations
```

Generated API client (checked into `clients/python/compose_api_client/`, the `compose-api-client` workspace package; excluded from ruff/mypy — never hand-edit):

```bash
make clients          # regenerates the spec (compose_api/api/spec/) and the client (clients/python/compose_api_client/)
make check-clients    # fails if either is stale; part of `make check`, so CI enforces it
LIB_DIR=<compose-api-client checkout>/compose_api_client make clients   # also writes the external 0.2.x repo
```

Web UI (`webapp/`, Nuxt 4 + Nuxt UI static SPA served by the API at `/ui`; [`docs/webapp.md`](docs/webapp.md)):
`make webapp-install`, `make webapp-dev` (:4200/ui/ against `make run`; `COMPOSE_API_URL=` for another API), `make webapp-check`, `make webapp-build`.
`webapp/app/api/schema.d.ts` is generated from the spec (`make clients` regenerates it; CI fails when stale) — never
hand-edit. Use standard libraries there (VueUse, openapi-fetch, PapaParse, Nuxt UI components) over ad hoc code.

Command line: `uv run compose-api --help` (the `compose-api-client[cli]` extra; guide and reference in
[`docs/cli.md`](docs/cli.md), `make cli-docs` regenerates the reference). Every API operation must be claimed by a
command (`@claims` in `compose_api_client/cli/commands.py`); `tests/client/test_cli.py` fails otherwise, so a new
endpoint needs a command in the same PR. Hand-written client code lives in `compose_api_client/ext/` and `cli/`,
which `make clients` preserves.

Generation is deterministic (`scripts/generate-api-client.sh`): the generator's post-hooks are off and the script
formats with the locked ruff and this repo's settings, so the committed client is byte-for-byte what `make clients`
produces. Never hand-edit the client; the plan for its package, the `ext` layer and the CLI is
[`docs/plan-cli.md`](docs/plan-cli.md).

Client release: publishing a GitHub release also publishes `compose-api-client` (clients/python, same version) to
PyPI via `.github/workflows/publish-client.yml`, a trusted publisher (OIDC, environment `pypi`; setup in
[`docs/plan-cli.md`](docs/plan-cli.md) §D).

Release & deploy: `make tag` (`tag.sh` bumps `pyproject.toml` + `compose_api/version.py`, commits, tags, pushes — the tag push triggers the image build workflow); `kustomize/scripts/build_and_push.sh` builds/pushes `ghcr.io/biosimulations/compose-api`.

**Deploys are GitOps.** Flux on the vxrails RKE2 cluster (configured in
[`virtualcell/vcell-fluxcd`](https://github.com/virtualcell/vcell-fluxcd), `clusters/vxrails/compose-api-*.yaml`) watches
this repo's `main`. It applies `kustomize/overlays/compose-api-rke` within a minute of a merge, with prune on. So
**merging to main deploys**: a pin bump in `kustomize/config/compose-api-rke/api.env`, or a release PR's `newTag`.
- **Image before tag:** push the release tag on the release PR's head commit and let the image build finish *before*
  merging. Otherwise Flux rolls out a tag that does not exist yet. The rolling update keeps the old pod serving, but
  the Kustomization reports unhealthy until the image appears.
- **Status / force a sync** (needs VPN): `flux get kustomization compose-api`;
  `flux reconcile kustomization compose-api --with-source`.
- **Manual fallback:** `make deploy` (`KUBECONFIG=~/.kube/kubeconfig_vxrails.yaml`). Flux reverts anything that
  diverges from `main` at its next reconcile.
- **Any API pod restart drops submissions still in flight:** a run still pulling or building its container stays
  `submitting` (#238). Avoid deploying while a first run of a new simulator image is in progress. Zenodo archiving is a **monthly rollup** (`zenodo-archive.yml`, 1st of the month): the reusable `virtualcell/zenodo-maint` workflow archives the latest GitHub *release*, if it isn't archived yet, under concept DOI 10.5281/zenodo.21127421. Run it by hand to archive now. Tags alone are never archived, and a published release also publishes the client to PyPI (above); keep `CITATION.cff` and `.zenodo.json` in step with the authors and version, as a weekly drift check flags mismatches.

## Test environment

- SLURM tests are **parameterised over a backend**, not skipped. Mark a test that needs a scheduler
  `@pytest.mark.slurm` and take the `slurm_backend` fixture; it runs against a throwaway SLURM cluster
  (`tests/fixtures/slurm_cluster/docker-compose.yml`, brought up per session) whenever Docker is present, with no
  key and no VPN. Add `@pytest.mark.cluster_only` when the test needs the real submit host — a real simulator
  image, the production partition, the real storage tree — and it will run only under
  `--slurm-backend cluster`. Building a container is *not* a reason on its own: the test cluster pulls from a
  registry and runs `singularity build --fakeroot`, covered by `tests/simulation/test_container_lifecycle.py`. `--slurm-backend` is repeatable, so passing both runs the body against each.
- **Never branch on `slurm_backend.kind` in a test body.** Differences between the backends are fields on the frozen
  `SlurmBackend` (`partition`, `qos`, `remote_base`, `can_build_singularity`); add a field rather than a branch, or
  the two backends grow separate implementations. `tests/common/test_slurm_conformance.py` is the drift alarm: it
  asserts the raw `sbatch`/`squeue`/`sacct` output shape our parsers assume, on every selected backend.
- The backend switch is a **settings override**, not an injected object, because three consumers reach for SSH
  independently. Use `override_settings(**fields)` from `compose_api/config.py`; it stacks partial layers removed by
  identity, so two fixtures overriding disjoint settings compose and overlapping ones raise.
- Postgres and MongoDB fixtures use **testcontainers**, so Docker must be running for most of the suite.
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
`/simulation` (submit), `/results` (status, results file, events, trace), `/core` (simulator/process/step catalogs),
`/curated` (pre-baked copasi/tellurium runs), `/simulations` (listing), `/datasets` (a run's files). Every endpoint sets an explicit `operation_id` because those become the generated
client's method names.

**Authentication** is optional Auth0 bearer, all in `compose_api/authentication.py`. Every router in `APP_ROUTERS`
sets `dependencies=[Depends(get_optional_principal)]` on its `RouterConfig` (keep its own prefix). A handler that
wants the identity adds an `OptionalPrincipal` parameter; FastAPI caches the dependency, so the token is still verified
once. No header means anonymous (`None`); any header that is present but invalid is a 401, never anonymous, which is
why the header is parsed by hand: `HTTPBearer(auto_error=False)` also returns `None` for a non-Bearer scheme. OpenAPI
security is document-level only (`_openapi_with_optional_bearer` in `api/main.py`). A per-operation `security`
entry, even `[{}, ...]`, makes openapi-python-client type that method as requiring `AuthenticatedClient`, a breaking
change for pbest. `openapi_spec.py` must use `app.openapi()` so the override reaches the checked-in spec. Settings are
`auth0_domain` and `auth0_audience`; the issuer is derived and the algorithm is fixed to RS256. Every active handler
also reaches the principal through a parameter of its own: `principal: OptionalPrincipal` where it only needs the
identity, or `caller: OptionalCaller` / `ReadableSimulation` where it reads through the authorization seam (a
structural test over `APP_ROUTERS` enforces it); submission handlers log `describe_caller(principal)`. `JwksCache` refreshes an unknown `kid` at most once per 30 s, the same back-off as an
expired cache, coalescing concurrent refreshes by counting *completed* refreshes. Deployment:
both API overlays load `config/compose-api-rke`; the local overlay overrides only the Auth0 keys via a
`behavior: merge` generator (`overlays/compose-api-local/auth0.env`); `config/compose-api-local` is used only by the
migration job. Every principal carries `roles`: always `DEFAULT_ROLE` ("user", the tenant role owned by auth0-pulumi's
biosim-platform stack) plus any names in the `ROLES_CLAIM` (`https://api.biosimulations.org/roles`) claim written by
the tenant's post-login "BioSim Roles" Action. Anonymous is `principal is None`, so no role. The only role checked is
`authorization.ADMIN_ROLE` ("admin"), which reads private simulations; none exist until submissions stamp an owner, so
it changes nothing yet. Keep the role and claim names in step with auth0-pulumi.

**HPC layer.** `SSHService` (asyncssh: `run_command`, `scp_upload`, `scp_download`) → `SlurmService`
(`sbatch --parsable`, `squeue`, `sacct` parsing into `SlurmJob`) → `SimulationServiceHpc`, which writes sbatch scripts
inline as f-string heredocs in `simulation_service.py` (one for simulation runs, one for `singularity build
--fakeroot` container builds). All remote paths come from `compose_api/simulation/hpc_utils.py` — `sims/`, `images/`,
`htclogs/`, `slurm_sbatch/` under the namespace directory. Never hardcode a remote path; add a helper there.
The container definition is generated by `pbest`, hashed (`get_singularity_hash`, md5 of the def file), and that hash
is the identity of a `SimulatorVersion` — an unseen hash triggers a container build job before the simulation runs.

**Registry and submission checks.** `compose_api/registry/manifest.yaml` is the registry of record (strategy
decision 5): pinned entries, each with `module_roots`, a curation `level` and `evidence`. `/simulation/run` calls
`registry.validation.validate_submission` before anything is recorded: it opens every composite document in the
upload (nested bundle archives included) and refuses any process address that is not `local:<module>.<Class>` under
a registered entry at level `tested` or higher in the `registry_env` bundle, with a 400 listing each address.
Non-`local` protocols and the arbitrary-import `local:!` form are refused even under `address_policy=warn`. The
container would otherwise run whatever it is sent, so this is the only check. Adding a simulator to what the service
runs means a manifest entry *and* the library in `simulation/simulator_registry.json`. `registry/catalog.yaml` is
generated (`uv run python -m compose_api.registry.catalog`, read-only against GitHub) and lists every vivarium-collective
catalog wrapper at `listed`; never hand-edit it — raising an entry means adding it to `manifest.yaml`, which wins.

**Job tracking.** An `HpcRun` row links a SLURM job id, a `correlation_id`, and a `JobType`
(`SIMULATION` / `BUILD_CONTAINER`). `JobMonitor` updates status two ways: a 5-second polling loop reconciling
`squeue`/`sacct` against running `HpcRun` rows, and the event ingester (below) on the same loop. The NATS path and its
`WorkerEvent`s were retired (docs/plan-observability.md step 1b); the `worker_event` table stays one release. Unparseable SLURM states are coerced to
`JobStatus.UNKNOWN` rather than raising. `internal_subscribe(queue, job_id)` lets in-process callers await transitions.

**Run events (`compose_api/observability/`, docs/plan-observability.md).** A run's trace id derives from its
`correlation_id` (`identity.py`), which is minted before `sbatch`. The job script (`simulation/job_script.py`, a pure
function with a bash test in `tests/observability/test_job_script.py`) writes the job span and `job.*` events to
`events/job.jsonl` and passes `PBG_*` variables to the container through an env file, so a process-bigraph >= 1.8.5
engine writes `events/engine.jsonl`. `EventIngester` tails those files on the mounted store in the `JobMonitor` loop
(byte cursors in `hpcrun.events_cursor`, deduplicated on `(trace_id, source, seq)`), and the API writes its own
`dispatch.*` / `slurm.*` events (`api_events.py`). All events follow process-bigraph's event schema (v1); the
parsing, span folding and Chrome Trace renderer are ported from viva-core.

**Datasets (`observability/datasets.py`, `api/routers/datasets.py`).** Every `artifact.written` event becomes a
`dataset` row (`DatasetsDatabaseService.register`, called by the ingester). The job script emits one per file under
`output/` (kept now) and for `results.zip`, with size and sha256, and one for the SLURM log `job.out` (kind
`log`, which simulation jobs now write in their experiment directory instead of `htclogs/`). A simulator's own event (any component but
`compose_api.job`) wins over that manifest. Paths are relative to the experiment directory, and
`resolve_content_path` keeps content reads inside it. A zarr store (`*.fenics` results bundle, `*.zarr`) is ONE
directory dataset: the manifest announces the directory, `/content` answers 409, and its files are read one at a time
through `/datasets/{id}/files/{subpath}` (Range, ETag, `no-cache`), so the web UI's viewers fetch chunks with no
server-side reduction ([`docs/plan-viewers.md`](docs/plan-viewers.md)). Listings filter with `authorization.readable_clause`.

**Persistence.** `DatabaseServiceSQL` (async SQLAlchemy + asyncpg) is a facade over three ORM executors:
`get_simulator_db()`, `get_hpc_db()`, `get_package_db()` (`compose_api/db/services/`, tables in `db/tables/`). Startup
calls `create_db()`: `metadata.create_all` (new tables), a stamp for a database alembic doesn't track yet (head if it
was empty, else the pre-tracking baseline), then `alembic upgrade head`. `create_all` never adds a column, so **a new
column on an existing table needs an alembic revision**; write it idempotently (`ADD COLUMN IF NOT EXISTS`), because a
fresh database already has it (`tests/common/test_migrations.py`). MongoDB settings and fixtures exist but the live path
is Postgres.

**Authorization.** Every route that reads something a simulation owns resolves it through
`compose_api.authorization.readable_simulation` (or `readable_simulation_ids`), which applies `can_read`. Ownership
(`simulation.owner_sub`, `visibility`) lives on the simulation only; runs, events and datasets inherit it. A simulation
the caller may not read is a 404. The caller is `get_caller`, which returns the verified principal from
`compose_api.authentication` (None when anonymous); tests override `get_caller` to pick one. Nothing stamps an owner
at submit yet (plan-observability step 5), so every simulation is public. See `docs/plan-observability.md` (O7, O8).

## Companion repositories

This service is one side of a three-package loop. `../pbest` is checked out next to this repo
(github.com/biosimulations/pbest) and has its own CLAUDE.md worth reading before changing anything below.

- **compose-api imports pbest at runtime.** `pbest.utils.input_types` supplies domain types used here directly —
  `ContainerizationFileRepr` (persisted in `db/tables/simulator_tables.py` and carried on `Simulator`),
  `ContainerizationEngine`, `ExperimentPrimaryDependencies`. `handlers.run_simulation` calls
  `generate_container_def_file(registry_dependencies(), ContainerizationEngine.APPTAINER)`; that def file's md5 is the
  `SimulatorVersion` identity, so **bumping the `pbest==0.6.3` pin changes the hash and triggers a fresh container
  build** on the next run (pbest's release script rewrites the `pbest_tag` baked into the generated def file). So
  does editing `compose_api/simulation/simulator_registry.json`, the library list baked into that image: a copy of
  `biosimulations/registry`'s `registry.json` pinned at the commit in `simulator_registry.py`, deliberately not
  pbest's `_default_registry_deps()`, which fetches the file live from that repo's `dev` branch.
  The pbest pin is exact and resolves from PyPI — the local `../pbest` working copy is *not* what compose-api runs against
  unless you deliberately install it editable, and it can sit on a different version than the pin.
- **pbest calls back over HTTP** using the published `compose-api-client` package (imported as `compose_api_client`,
  currently 0.2.0), generated from this repo's OpenAPI spec, defaulting to `https://compose.cam.uchc.edu`. It uses
  `run-simulation`, `get-simulations-status-batch`, `get-simulation-status`, and `get-simulation-results-file`; those
  `operation_id`s *are* pbest's function names, so renaming one is a breaking change downstream. pbest's
  `_normalize_pbg_paths` is what packs a local process-bigraph document into the `experiment.omex` that arrives at
  `/simulation/run`, and its batch path submits with `batch_submission=True` then polls the batch status endpoint —
  which is why the batch branch in the sbatch template uses the smaller batch partition/QoS and 1 CPU / 1 GB.
- **Changing a request or response model is a four-step release**: regenerate the spec and client here, publish
  `compose-api-client`, bump it in pbest, then bump the `pbest` pin here. `make clients` writes the in-repo
  `clients/python/compose_api_client/` and, only when `LIB_DIR` is set, the separate
  [compose-api-client](https://github.com/biosimulations/compose-api-client) repo (PyPI 0.2.x, what pbest uses). That
  package also carries a hand-written `utils/run_simulation_and_wait.py`; the script preserves it.
- The production host is `compose.cam.uchc.edu` in all three places that must agree: the RKE ingress
  (`kustomize/overlays/compose-api-rke/ingress.yaml`), `ServerMode.PROD` plus `APP_ORIGINS` here, and pbest's default
  client base URL. Changing it means changing all three.

## Conventions

- ruff, line length 120, with a broad rule set (bandit `S`, bugbear `B`, tryceratops `TRY`, …); `make check` must be
  clean. `alembic/`, `documentation/`, and the generated parts of `clients/python/compose_api_client/` are excluded.
- mypy runs `--strict` over `compose_api` and `tests`; use `typing.override` on interface implementations, as the
  existing services do. (It moved from `typing_extensions` when the ruff target went to `py313`; the floor in
  `requires-python` is 3.13.2 and the runtime is 3.14.)
- Domain models are pydantic (`compose_api/simulation/models.py` subclasses a local `BaseModel` that adds
  `as_payload()`); enums are `StrEnum` when their string value is wire- or path-visible.
