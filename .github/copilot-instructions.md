# Copilot instructions for compose-api

## Project commands

This project requires Python 3.13.2 or newer (CI runs Python 3.13 and 3.14) and uses `uv` for dependency management. Run Python tools through `uv run`.

```bash
make install       # uv sync and install pre-commit hooks
make run           # start FastAPI/Uvicorn on http://localhost:8000 with reload
make check         # locked dependency check, pre-commit, mypy --strict, and deptry
make test          # pytest with coverage
make docs-test     # build MkDocs and fail on warnings
make docs          # serve MkDocs locally
```

Useful targeted commands:

```bash
uv run python -m pytest tests/simulation/test_scheduler.py::test_name -s
uv run python -m pytest tests/common -k nats
uv run mypy                         # configuration and file set come from pyproject.toml
```

Most integration tests use Docker-backed testcontainers for Postgres, NATS, MongoDB, and/or the throwaway SLURM cluster. Scheduler tests are marked `slurm` and default to the container backend when Docker is available:

```bash
uv run python -m pytest tests -m "not slurm"
uv run python -m pytest tests -m slurm
uv run python -m pytest tests -m slurm --slurm-backend container --slurm-backend cluster
```

Use `cluster_only` only for tests requiring the real submit host, production partition, storage tree, or simulator image. Do not branch test bodies on `slurm_backend.kind`; express backend differences as fields on the frozen `SlurmBackend` fixture.

For database model changes, generate and apply an Alembic migration with `make db-migrate msg="description"` and `make db-upgrade`. `init_standalone()` currently calls `create_db()` at startup, but existing deployments still require a migration. Regenerate the OpenAPI spec and checked-in client with `make clients`; do not hand-edit `compose_api/api/client/`.

## Architecture

`compose-api` is a FastAPI service for reproducible biological workflows. It does not execute simulations locally: requests are packaged and submitted to a remote SLURM cluster, where Singularity/Apptainer containers run the workload.

The main request path is:

1. `compose_api/api/main.py` creates the FastAPI app, starts services in its lifespan, and dynamically registers the routers listed in `APP_ROUTERS`.
2. A router in `compose_api/api/routers/` validates the request and delegates to `compose_api/simulation/handlers.py`.
3. The handler uses the database facade, simulation service, and job monitor. It generates a pbest container definition, hashes it as the simulator-version identity, records the simulation, and schedules the actual work as a background task.
4. `SimulationServiceHpc` uploads input and generated SLURM scripts through `SSHService`, while `SlurmService` submits jobs and parses `squeue`/`sacct`.
5. `JobMonitor` reconciles SLURM state on a five-second polling loop and optionally consumes NATS worker events. It updates `HpcRun` records and supports in-process waiters used during container builds.
6. `DataService` retrieves the remote `results.zip` after completion.

Persistence is PostgreSQL via async SQLAlchemy. `DatabaseServiceSQL` fronts separate executors for simulator, HPC-run, and package data in `compose_api/db/services/`; ORM tables are in `compose_api/db/tables/`. MongoDB-related settings and fixtures remain in the repository, but the live application path uses PostgreSQL.

The module-level services in `compose_api/dependencies.py` are the application’s dependency-injection mechanism: database, simulation, job monitor, data service, and Postgres engine are initialized during the FastAPI lifespan and cleared during shutdown. Preserve late imports there because the dependency and simulation-service modules have intentional circular-import boundaries.

The API prefixes are `/simulation`, `/results`, `/core`, and `/curated`. Each router must expose a module-level `config = RouterConfig(...)`, and every endpoint must have an explicit `operation_id`. These operation IDs are public names used by the generated client and by the companion `pbest` package; changing one is a downstream breaking change.

## Repository-specific conventions

- Resolve configuration through `get_settings()` from `compose_api/config.py`. It loads the git-ignored `assets/dev/config/.dev_env`, then optional `CONFIG_ENV_FILE` and `SECRET_ENV_FILE` files. Settings are cached; environment changes require a process restart. Tests should use `override_settings(**fields)` rather than replacing a settings object.
- `namespace` selects both the HPC storage subtree and the data-service implementation. Remote paths must be built through helpers in `compose_api/simulation/hpc_utils.py`; do not hardcode paths for `sims`, `images`, `htclogs`, or `slurm_sbatch`.
- Use the existing service-fixture pattern: save the module-level singleton, set the test service, yield, then restore the previous value. Fixtures are defined under `tests/fixtures/` and re-exported from `tests/conftest.py`.
- SLURM parser assumptions are contractually tested in `tests/common/test_slurm_conformance.py` against each selected backend. If scheduler output or parser behavior changes, update the conformance coverage rather than adding backend-specific branches.
- Container definitions come from pbest and their MD5 hash is the `SimulatorVersion.container_def_hash`. A pbest version change can therefore trigger a new container build; keep the exact `pbest` pin and this identity behavior in mind when changing simulation setup.
- The batch submission path intentionally uses separate SLURM partition/QoS and reduced resources. Preserve that distinction when changing sbatch templates.
- Domain request/response models are Pydantic models in `compose_api/simulation/models.py`; the local base model provides `as_payload()`. Use `StrEnum` for enums whose values are exposed on the wire or in paths.
- The generated client under `compose_api/api/client/` is excluded from Ruff and mypy and must be regenerated, not manually edited. `compose_api/api/openapi_spec.py` writes the OpenAPI artifact; `scripts/generate-api-client.sh` handles client generation and may also write to the separate client repository named by `LIB_DIR`.
- Ruff targets Python 3.13, uses a 120-character line limit and a broad lint set; `alembic/`, documentation, and generated client code are excluded. Mypy is strict over `compose_api` and `tests`.
- For API model or operation changes, update the spec/client workflow and account for the companion release sequence: publish `compose-api-client`, update it in pbest, then update the pinned pbest version here.

## Deployment and release touchpoints

`make tag` updates the project version, commits, tags, and pushes; the tag triggers the container workflow. Kubernetes manifests live under `kustomize/`, and `make deploy` applies the production RKE overlay. The production host is repeated in the API configuration, ingress, and pbest defaults, so host changes must be coordinated across all three repositories.
