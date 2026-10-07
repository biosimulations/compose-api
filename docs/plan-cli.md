# CLI: a `compose-api` command line on a generated httpx client

**Status (2026-10-07): planned and approved by Jim; step A in review.** Three PRs, each merged on green with a merge
commit. Publishing to PyPI and deploying are separate goes from Jim.

| Step | What | State |
|---|---|---|
| A | Generation pipeline: deterministic, in-repo, drift-checked in CI; regenerate the stale client | **#205** |
| B | `compose-api-client` as a workspace package: the generated client plus a hand-written application layer (`ext`) | — |
| C | The `compose-api` CLI on `ext` and the generated client; a spec-coverage test | — |
| D | Docs (`docs/cli.md`), `CLAUDE.md`, strategy.md 2b; release with 0.7.0 | — |

## Context

compose-api has no command line. Today a user drives it with curl, the generated client in Python, or pbest's
`run_simulation_and_wait`. The goals:

- **Exercise every operation.** One command per operation; a test fails if the spec gains an operation the CLI does
  not claim.
- **Build on a client generated from the OpenAPI spec**, httpx-based, which pytest drives against the FastAPI app
  in-process.
- **Two layers above the generated code, with different concerns:**
  - an application layer for programs that integrate the service (waiting, downloading, typed errors);
  - the CLI, for people and scripts (output formats, exit codes, configuration).

The precedent is sms-api's (viva-api's) plan for its own core CLI, decision **D8** of
[`plan-core.md`](https://github.com/vivarium-collective/viva-api/blob/main/docs/plan-core.md): "an independent CLI
targeting only core, built on the OpenAPI client generated from the core spec … no hand-rolled URLs, no server
imports". That CLI is deferred to its Phase 2 (P8) and not built yet. This plan is the same shape, done first here.

## What exploration found (read-only, 2026-10-07)

### The API: 12 operations

There is no auth and there are no websockets. `compose_api/api/main.py` mounts `curated`, `simulation`, `results`
and `compute` (prefix `/core`).

| Method | Path | operationId | Notes |
|---|---|---|---|
| GET | `/health` | `check_health_health_get` | `{docs, version}` |
| GET | `/version` | `get_version_version_get` | |
| POST | `/simulation/run` | `run-simulation` | multipart `uploaded_file`; `interval_time`, `batch_submission`, `simulator`; 400 `detail` is a string or `{message, violations}` |
| POST | `/curated/copasi` | `run-copasi` | multipart `sbml`; `start_time`, `duration`, `num_data_points` |
| POST | `/curated/tellurium` | `run-tellurium` | multipart `sbml`; `start_time`, `end_time`, `num_data_points` |
| GET | `/results/simulation/status` | `get-simulation-status` | 404 until the SLURM job exists |
| GET | `/results/simulations/status/batch` | `get-simulations-status-batch` | **a GET with a JSON body** (`list[int]`) |
| GET | `/results/simulation/results/file` | `get-simulation-results-file` | zip |
| GET | `/results/simulator/build/status` | `get-simulator-build-status` | 404 as above |
| GET | `/core/simulator/list` · `/core/processes/list` · `/core/steps/list` | `get-simulator-list` · `get-processes-list` · `get-steps-list` | |

pbest calls four of these by operationId (`run-simulation`, `get-simulations-status-batch`, `get-simulation-status`,
`get-simulation-results-file`). **Renaming any of them breaks pbest.**

### The generated client is stale, and nothing notices

- **Generator:** `openapi-python-client` 0.29.1 (dev, `<0.30`), run by `scripts/generate-api-client.sh` from
  `make clients`. Its output, `compose_api/api/client/`, is committed and ships inside the server wheel.
  - It gives attrs `Client`/`AuthenticatedClient` wrapping `httpx.Client` and `httpx.AsyncClient`, with `sync`,
    `sync_detailed`, `asyncio` and `asyncio_detailed` per operation, and 23 typed models.
  - Tests drive it in-process: `tests/fixtures/api_fixtures.py::in_memory_api_client` installs
    `httpx.AsyncClient(transport=ASGITransport(app=app))`.
- **Stale:** the client was generated 2026-09-08; the spec was regenerated 2026-10-06.
  - `run_simulation` has no `simulator` parameter (#190).
  - No 400/404 is parsed: a 404 raises `UnexpectedStatus` or returns `None`.
- **Not reproducible.** Regenerating today differs from the committed tree in every file, mostly formatting:
  - The committed tree is raw template output (unsorted imports, an unused `from urllib.parse import quote`).
  - A regeneration on a machine with `ruff` on PATH runs the generator's default post-hooks, which format with ruff's
    defaults, not this repo's settings.

  So the output depends on the machine, and a CI drift check is impossible until the post-hooks are pinned.
- **`make clients`** has three problems:
  - It refuses to run without `LIB_DIR`, because it also writes into the separate `compose-api-client` repository
    (PyPI 0.2.0, which pbest uses).
  - It calls a bare `openapi-python-client`.
  - It runs the spec script with `python3` rather than `uv run`.
- **No CI step checks the spec or the client.**

### Packaging intent already decided

[`strategy.md`](strategy.md) plans one uv workspace with three distributions:
- `viva-toolkit`: pbest renamed, the local-or-remote *run* command line;
- `compose-api-client`: the generated client plus its one hand-written helper, outside the generated tree;
- `compose-api`: the service.

Phase 2b's gate is "`make clients` writes only in-repo". This plan does 2b's client half. It doesn't wait for pbest to
be absorbed.

### atlantis (sms-api / viva-api): what to copy and what not to

`atlantis` is viva-api's typer CLI (`app/cli.py`, about 3,700 lines). It already has a `compose` group with the same
verbs: `run`, `status` with several IDs, `results`, `simulators`, `processes`, `steps`, `build-status`, `copasi` and
`tellurium`.

**Worth copying:**
- typer sub-apps per noun (`cli.add_typer(compose_cli, name="compose")`);
- one error handler (a decorator plus `main()`) that renders connection, HTTP, JSON and other errors as a panel and
  pulls `detail` out of FastAPI error bodies;
- exit codes 1 (error), 2 (bad input), 130 (Ctrl-C);
- opt-in polling with a status line per tick and a final panel;
- a spinner while submitting;
- `CliRunner` tests with the service factory patched, plus `httpx.MockTransport` for the HTTP layer.

**Not worth copying:**
- **Its HTTP layer is hand-written.** `E2EDataService` builds URLs from string literals and returns the server's own
  pydantic models. Its route-drift test explains why: atlantis ships inside viva-api, and that generator returned bare
  `Any` for 20 of 20 operations.
  - Neither reason holds here. A standalone client cannot import server models, and this repo's generated operations
    are typed.
  - The hand-written layer also needs an AST test just to notice that a URL stopped existing. Generated code goes
    stale too, but then a drift check finds it mechanically.
- **No global options:** every command repeats `--base-url`, and there is no output-format option.
- **Packaging:** the CLI ships in the server's distribution with typer, textual and marimo as core dependencies, so
  `pip install viva-api` installs the server stack. strategy.md forbids that here: "a laptop install must not pull the
  server".

## Decisions

| # | Decision | Why |
|---|---|---|
| C1 | **Keep `openapi-python-client`**, pinned, with a committed config. | httpx-native, sync and async; typed attrs models; `httpx_args` and `set_*_httpx_client` accept `ASGITransport`/`MockTransport`, so pytest needs no server. Already in use. **Rejected:** openapi-generator (Java, urllib3 by default; `openapitools.json` is a leftover to delete); a hand-written httpx client (atlantis's road, above); commercial SDK generators (not justified for 12 operations). |
| C2 | **The generated code is never edited; behaviour goes in `ext`.** | Regeneration must be free. pbest's `utils/run_simulation_and_wait.py` shows what happens otherwise: hand-written code inside a generated tree, with a standing warning not to overwrite it. |
| C3 | **The CLI is hand-written typer over `ext`, with a spec-coverage test.** | A spec-driven runtime CLI (restish-style) gets coverage for free but has poor UX: raw query and body flags, no `--wait`, no file handling. The CLI's real concerns are presentation, waiting and files. The coverage test gives back what that approach would have guaranteed. |
| C4 | **`compose-api-client` is a workspace package with an optional `[cli]` extra** (typer, rich). The command is `compose-api`. | The base install is httpx and attrs only, for applications; strategy.md's packaging constraint. The command drives the service; `viva-toolkit` builds and runs documents. They are two tools with two names. |
| C6 | **`clients/python` comes in from [compose-api-client](https://github.com/biosimulations/compose-api-client) at tag 0.2.0 by `git subtree`, with its history** (30 commits, Ezequiel Valencia), and the root overrides pbest's `compose-api-client==0.2.0` pin so it resolves to the workspace package. *(Found while starting B, 2026-10-07.)* | pbest pins the client exactly, so a workspace package of that name at any other version cannot resolve, and two packages cannot both install `compose_api_client`. The override is safe for the service: it imports only `pbest.utils.input_types` and the containerization code, never `pbest.execution.remote` (the client's one user), and the regenerated client keeps every name that module uses (`Client`, `api.simulation.run_simulation`, `models`, `types.File`, `utils.run_simulation_and_wait`). Bringing it in with history is strategy.md's rule 1 ("merge with history, never by copying") applied to phase 2b. |
| C5 | **The API is unchanged by this work.** The GET-with-body batch endpoint stays. | Moving `ids` to the query string would change pbest's call signature. That's a separate decision, recorded in §Open questions. |

## Plan

### A. Generation pipeline (PR 1)

- `scripts/openapi-python-client.yaml`, committed:
  - `post_hooks`: `ruff check --fix` and `ruff format`, run through `uv run` against **this repo's** ruff
    configuration (line length, isort).
  - `project_name_override` / `package_name_override` for the target package.
  - The output is then the same on every machine.
- `make clients`:
  - `uv run python compose_api/api/openapi_spec.py`, then `uv run openapi-python-client generate --config …`, writing
    only in-repo.
  - `LIB_DIR`, when set, also writes the external repository, for the 0.2.x line pbest pins; the 0.2.x repository is
    retired at strategy phase 5.
- **`make check-clients`**, added to `make check` so CI runs it in `quality`:
  1. generate the spec and the client into a temporary directory;
  2. `diff` both against the committed copies;
  3. on any difference, fail with "run `make clients`".
- Regenerate and commit the new client. It picks up `simulator` and the 400/404 handling. Adjust the few tests that
  relied on a 404 raising.
- Delete `openapitools.json` and the commented-out openapi-generator lines.

### B. The `compose-api-client` package (PR 2)

`clients/python/` is a uv workspace member: distribution `compose-api-client`, version locked to the service.

- **`compose_api_client/` (generated):** the client moves here from `compose_api/api/client/` (C6: by subtree from
  the external repository, then regenerated in place; its hand-written `utils/` is kept).
  - Nothing outside this repository imports `compose_api.api.client` (pbest imports `compose_api_client`), so the
    in-repo copy is deleted rather than shimmed; the server's tests import `compose_api_client`.
- **`compose_api_client/ext/` (hand-written, outside the generated tree).** Its only dependencies are httpx and attrs.

| Piece | What |
|---|---|
| `ComposeSession(base_url=… \| client=…, timeout, retries)` / `AsyncComposeSession` | Context managers that own a `Client`. `ComposeSession.in_process(app)` builds the `ASGITransport` client tests use; `AuthenticatedClient` when a token is given (reserved for #192's Auth0). |
| `submit(file, simulator=, interval=, batch=)`, `submit_curated(engine, sbml, …)` | The `SimulationExperiment` |
| `status(id)` → `JobState` | `.status`, `.terminal`, `.ok`, `.slurm_job`. A 404 means `SUBMITTING`, not an error, until a deadline. |
| `wait(id, poll=, timeout=, on_update=)`, `build_status(id)`, `wait_build(id)` | The final `HpcRun` |
| `results(id) -> bytes`, `download(id, dest, extract=False)` | The zip, saved or unpacked |
| `run_and_wait(...)` | Submit, wait, download. Replaces pbest's helper and the tests' `check_experiment_run`. |
| Errors | `NotFound`, `BadRequest(detail, violations)`, `ServerError`, `ApiTimeout`, mapped from the `*_detailed` responses. |

`tests/simulators/utils.py::check_experiment_run` moves onto `run_and_wait`. That makes the service's own tests the
first user of `ext`.

**Later, not in this plan:** an ensemble helper (seed blocks, a manifest, resume, retry, splitting on timeout) can
generalise viva-pde-particle's `compose_client.EnsembleRun` once this ships on PyPI.

### C. The CLI (PR 3)

`compose_api_client/cli/`, entry point `compose-api = compose_api_client.cli:main`, installed with
`compose-api-client[cli]`.

**Global options**, on the root callback and not repeated per command (unlike atlantis):

| Option | Env | Default |
|---|---|---|
| `--url` | `COMPOSE_API_URL` | `https://compose.cam.uchc.edu` |
| `--timeout` | `COMPOSE_API_TIMEOUT` | 300 s |
| `--output {table,json,yaml}` | `COMPOSE_API_OUTPUT` | `table` on a TTY, `json` when piped |
| `--token` | `COMPOSE_API_TOKEN` | none (reserved for #192) |
| `--verbose` / `--quiet` | | `--verbose` logs the HTTP exchanges |

**Commands.** Each operationId belongs to exactly one command:

| Command | Operation(s) |
|---|---|
| `health`, `version` | `check_health_health_get`, `get_version_version_get` |
| `simulators list` · `processes list` · `steps list` | `get-simulator-list` · `get-processes-list` · `get-steps-list` |
| `run FILE [--simulator NAME] [--interval T] [--batch] [--wait] [--download DIR] [--extract]` | `run-simulation` |
| `curated copasi SBML --start --duration --points [--wait …]` | `run-copasi` |
| `curated tellurium SBML --start --end --points [--wait …]` | `run-tellurium` |
| `status ID… [--watch]` | one ID: `get-simulation-status`; several: `get-simulations-status-batch` |
| `results ID [-o FILE \| --extract DIR]` | `get-simulation-results-file` |
| `wait ID… [--poll S] [--timeout S]` | status, through `ext.wait` |
| `build-status ID [--wait]` | `get-simulator-build-status` |
| `openapi [--server] [--diff]` | The bundled spec; `--server` fetches the live `/openapi.json`; `--diff` reports client/server skew |

**Behaviour:**
- **Exit codes:**

  | Code | Meaning |
  |---|---|
  | 0 | Success, or the job completed |
  | 1 | The job ended failed, timed out, out of memory or cancelled |
  | 2 | Usage error |
  | 3 | API error, with `detail` and the `violations` rendered |
  | 4 | Not found |
  | 130 | Interrupted |

  `run --wait` returns the job's outcome, so `compose-api run x.omex --wait && …` can be scripted.
- **Waiting:** a rich status line per poll on a TTY and nothing when piped; a final panel or JSON record.
- **Errors:** one handler, rendering as atlantis does; `--verbose` adds the traceback.
- **Registry:** commands declare their operationIds with a decorator, `@claims("run-simulation")`. The coverage test
  reads that registry.

### D. Tests, docs, release

- **Coverage test.** It fails CI on drift in either direction:
  - every operationId in the committed spec is claimed by exactly one command;
  - the registry names no operation the spec lacks.
- **CLI tests:** `CliRunner` with the session factory pointed at `ComposeSession.in_process(app)`, a fixture beside
  `in_memory_api_client`. They cover:
  - each command once;
  - the output formats;
  - every exit code;
  - `run --wait --download` against the existing SLURM-mocked fixtures;
  - the rendering of 400 violations and 404s.
- **`ext` tests:** polling, deadlines and error mapping through `httpx.MockTransport`; downloads into `tmp_path`.
- **Docs:**
  - `docs/cli.md`: install, connect, a tutorial (run, wait, download), and a command reference generated by
    `typer compose_api_client.cli utils docs`;
  - a `CLAUDE.md` regeneration section;
  - the strategy.md 2b row.
- **Release:** with the service, 0.7.0, alongside #192. Publishing `compose-api-client` 0.3.0 to PyPI is a separate go.

## Verification

- `make check-clients` passes on a clean tree. Adding a route without running `make clients` makes it fail.
- `uv run pytest -m "not slurm"` is green, including the coverage test and `tests/cli/`. CI `tests-slurm` is green.
- `uv build` for `clients/python` installs into a clean venv with neither FastAPI nor SQLAlchemy. Then
  `pip install 'compose-api-client[cli]'` gives `compose-api --help`.
- Against production (0.6.0):
  1. `compose-api health`
  2. `compose-api simulators list`
  3. `compose-api run experiment.omex --simulator viva-pde-particle --wait --download out/`, which exits 0 and leaves
     the `.pber` in `out/`
  4. `compose-api status <id> --output json`
  5. `compose-api openapi --server --diff`, which reports no skew

## Risks

- **Moving the client changes import paths for pbest's 0.2.x line.** Mitigation: the external repository keeps
  publishing 0.2.x from `LIB_DIR` until strategy phase 5. The in-repo shim covers this repository's own imports.
- **Generator upgrades reformat everything.** Mitigation: pin `<0.30` and upgrade deliberately in its own PR. The drift
  check makes the diff visible.
- **The FastAPI 0.141 upload schema needs `_restore_binary_format`** (generator issue #1417). The drift check compares
  the post-processed spec, so a fix upstream only shows up as a clean diff.

## Non-goals

- Auth: `--token` is reserved; #192 decides the flow.
- A TUI or GUI (atlantis has both; not needed here).
- Folding atlantis's `compose` group into this CLI. viva-api could later delegate to `compose-api-client`, which is
  viva-api's decision.
- Ensembles: a later `ext` helper; viva-pde-particle has its own today.

## Open questions

1. **The batch-status endpoint:** keep the GET-with-body, or add a query-string form (`?ids=1&ids=2`) beside it? The
   addition would be non-breaking, the replacement would break pbest. Proposed: add the query form in 0.7.0 and keep
   the body form until pbest moves.
2. **The command name:** `compose-api` (proposed: names the service), or `compose`, which is shorter but generic and
   collides with `docker compose` muscle memory?
3. **When the 0.2.x external repository stops being written:** at strategy phase 5 (proposed), or as soon as pbest pins
   the in-repo 0.3?
