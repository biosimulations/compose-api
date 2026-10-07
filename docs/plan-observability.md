# Observability: run traces from process-bigraph events, and datasets a run advertises

**Status (2026-10-07): steps 0–4 and 1b merged (#212–#216, viva-pde-particle#49) and deployed in 0.7.0/0.7.1, plus a simulation listing (#220); follow-ups for open questions 2 and 5 in review; step 5 waits on #192.** One PR per step, each merged on green with a merge commit.
Deploying is a separate go from Jim.

| Step | What | State |
|---|---|---|
| 0 | This document | **done** #212 |
| 1 | Trace identity before submission (O1); owner and visibility (O7); the authorization seam on every simulation read (O8); migrations that run at startup | **done** #213 |
| 1b | Retire NATS and `worker_event` (the subscriber, settings, the k8s deployment and its public NodePort) | **done** #216 |
| 2 | Events: job-script activation (O2), API and job-script events (O3), the file-tailing ingester (O4), events and trace routes, `ext`, CLI | **done** #214 |
| 3 | Datasets: job-script manifest and `artifact.written` registrar (O5), store-relative content (O6), dataset routes, `ext`, CLI | **done** #215 |
| 4 | Producer side in viva-pde-particle: `artifact.written` per result file, inside a `task` span | **done** viva-pde-particle#49; live once its image is rebuilt and the prebuilt pin bumped |
| 4b | Follow-ups from the first production runs: per-process engine event files (open question 2; process-bigraph#229), the SLURM log as a dataset (open question 5) | **in review** |
| 5 | Auth hookup after #192: stamp the owner at submit, a real `can_read` policy, visibility | blocked on #192 |

## Context

compose-api tells a user a job's SLURM status and hands back one `results.zip`. It cannot say what a run did, where
it failed, or what it produced. Two ideas from the **viva-core** project answer that:

- **Tracing.** process-bigraph ≥ 1.8.5 (`process_bigraph/events.py`) emits structured events shaped like
  OpenTelemetry: every event carries `trace_id`, `span_id` and `parent_span_id`; spans nest; context passes to child
  processes as a W3C `traceparent`. viva-core ingests those events into tables and serves them as event lists, span
  trees and Chrome Trace (Perfetto) files.
- **Datasets.** A run advertises each artifact it writes with an `artifact.written` event; viva-core turns those into
  queryable dataset rows with a content route.

Auth is coming (Auth0, #192). Once it lands, simulations, their events and their artifacts need owners and permission
checks. This plan builds both features so that the permission check is already in the path when auth arrives.

## What exploration found (read-only, 2026-10-07)

### compose-api today

- **No owner anywhere.** No table has an owner or user column, and status and results are read by numeric id with no
  check. #192 verifies a bearer token and injects an optional principal into `POST /simulation/run`, but only logs it;
  its own doc says authentication "does not attach the simulation to that caller".
- **A progress pipeline that cannot work.** `JobMonitor` subscribes to NATS (`worker.events`) and stores
  `WorkerEventMessagePayload {correlation_id, sequence_number, time, mass}` in `worker_event`
  (`job_monitor.py:36-60`, `db/tables/hpc_tables.py:94`). But the simulation's `correlation_id` is minted *after*
  `sbatch` (`handlers.py:192`) and never passed to the container, so no job can emit a matching event. NATS is off by
  default, and the events route in `routers/results.py` is commented out.
- **No artifacts, and failures leave nothing.** The job script (`simulation_service.py:93-124`) runs under `set -e`,
  zips `output/` into `results.zip`, then deletes `output/`. A failed run stops before the zip, and the only trace is
  the SLURM `.out` in `htclogs/`, which no endpoint serves.
- **The store is mounted.** The API pod reads results straight from the shared filesystem
  (`/mnt/projects/CRBM/compose_api/{namespace}`, `DataServiceHpc.get_results_zip`). Anything a job writes into its
  experiment directory, the API can read without SSH.
- **Migrations don't run.** Startup calls `create_all`, which creates new tables but never adds columns; the call to
  `upgrade_db` is commented out (`dependencies.py:165-168`), and the k8s migration Job still says `poetry run`.
- **The engine version gap.** Simulator images decide whether events exist. viva-pde-particle's image is on
  process-bigraph 1.8.5 and emits. Images built from pbest are on 1.0.5, which has no `events.py`.

### process-bigraph events (≥ 1.8.5)

- One JSON object per line:
  `{v, ts, seq, source, component, event, level, trace_id, span_id, parent_span_id, global_time, wall_time, baggage, tags, payload}`.
- Engine events: `run.start`/`run.end` (rate-limited), `tick` (heartbeat), `structure.changed`, `process.exception`,
  `task.start`/`task.end`, `span.start`/`span.end` (with `duration_s`, `status`, `error`), `sink.error`; opt-in
  `process.invoke` and `process.timing`.
- Configured entirely by environment: `PBG_EVENT_SINKS` (`stdout`, `none`, `file:<path>`, a registered scheme, or
  `module:attr`), `PBG_TRACEPARENT`, `PBG_TRACE_BAGGAGE`, `PBG_EVENT_TAGS`, `PBG_EVENT_HEARTBEAT_S`,
  `PBG_EVENT_DETAIL`, `PBG_EVENT_SOURCE`. Off in the library, stdout in the CLI entrypoints.
- It never raises into the simulation, and it knows nothing about the domain: caller identity travels only in the
  opaque `baggage`.
- `artifact.written` is not an engine event. It is a convention between a producer and the ingester.

### viva-core: what to take and what not to

| | viva-core | compose-api |
|---|---|---|
| Transport | Runs write `*.jsonl` objects to object storage; a scheduler tick lists them under the run's prefix and reads past a byte cursor (`viva_core/events/ingest.py`) | The same tailing, on a **mounted filesystem**: no object store, no new transport |
| Who emits | Images that configure a process-bigraph sink | Arbitrary simulator images; many never will |
| Artifacts | `artifact.written` events (`viva_core/datasets/registry.py`) plus a walk of the output tree that classifies files by name (`viva_core/datasets/walk.py`) | The **job script's manifest** is the primary feeder; events refine it |
| Ownership | An `OwnerRef(owner_kind, owner_id)` on each record (`viva_core/datasets/models.py`); `viva_core/api/auth.py` is explicitly "a seam, not a security boundary" | One owner per simulation that everything **inherits**, behind a check that is in the path from the first PR |
| Identity | `trace_id` derived from the correlation id so it is known before the row exists (`viva_core/events/events_env.py`) | **Take as is** |

**Take:** the event schema, the derived trace identity, the ingest rules (byte cursors, dedup on
`(trace_id, source, seq)`, drop `tick` and `debug`, fold span events into spans, close spans left open when the run
ends), the span tree and Chrome Trace renderer, the `artifact.written` payload, and the rule that an event-sourced
dataset row is never overwritten by a lower-precedence feeder.

**Don't take:** object storage, owner pairs on every row, an identity header, a separate walk scheduler.

**Reuse by porting.** viva-core already keeps this logic behind Protocols (`EventStore`, `ArtifactRegistrar`,
`DatasetWriter`/`DatasetStore`), and its pure functions have no storage dependency: `parse_event_lines`,
`apply_span_events`, `build_span_tree`, `storable_events`, `trace_id_from_correlation`, `traceparent`, and
`events/chrome_trace.py`. viva-core is not published as a package, so these are ported into
`compose_api/observability/`, each citing its source. Depending on viva-core instead is open question 6.

## Decisions

| # | Decision | Why |
|---|---|---|
| O1 | **The trace identity is fixed before submission.** Mint `correlation_id` before `sbatch`; `trace_id = sha256(correlation_id)[:32]`, and the job span id derives from it too (viva-core's `trace_id_from_correlation`). `hpcrun` gains `trace_id`, `events_cursor` (JSONB), `last_event_at`, `exit_code`. | The job script must carry the trace context, and it is written before the `hpcrun` row exists. Deriving it means no second write and no race. |
| O2 | **Activation is the job script's job; capability is the image's.** The script always passes `singularity --env` with `PBG_TRACEPARENT`, `PBG_TRACE_BAGGAGE` (`simulation_id`, `experiment_id`), `PBG_EVENT_TAGS=backend=slurm` and `PBG_EVENT_SINKS=file:/experiment/events/engine.jsonl`. | Images need no compose-api knowledge, and an image without events simply ignores the variables. File only, not stdout, so the SLURM log stays readable. |
| O3 | **Every run has a trace, even if its image emits nothing.** The API writes its own events straight to the database with `source=api`: `dispatch.accepted`, `dispatch.submitted`, and `slurm.<state>` on each `JobMonitor` transition. The job script appends `job.start` (host, SLURM job id) and `job.end` (exit code, wall seconds) to `events/job.jsonl` from a bash `emit` helper under `trap … EXIT`. | Queue wait, run time and the failure point for every simulator, including pbest images. The `trap` records a failure that `set -e` would otherwise make silent. |
| O4 | **Ingest by tailing files on the mount.** An ingest tick in the `JobMonitor` loop reads `events/*.jsonl` past a per-file byte cursor, for runs that are running or ended within a grace window, and parses complete lines only. It validates `trace_id`, stores events into `run_event` (deduplicated on `(trace_id, source, seq)`, dropping `tick` and `debug`), and folds span events into `run_span`; spans still open when the run ends close as `unknown`. **NATS and `worker_event` are retired.** | The store is already mounted, so no transport is needed, and jobs never have to reach the API from the HPC network. The ingest rules are viva-core's. |
| O5 | **Two dataset feeders, the manifest primary.** After the run the job script writes `artifacts.jsonl`, one line per file under `output/`: `{path, bytes, sha256}`. Media type and kind are inferred from the suffix. An `artifact.written` event (viva-core's payload: `uri, kind, name?, view?, bytes?, sha256?, attributes{}, error?`) refines its row with kind, display name and attributes, and **wins over the manifest**. The job script keeps `output/` and still writes `results.zip`. | Most simulator images will never emit `artifact.written`, so the manifest makes datasets work for all of them on day one. The zip keeps the existing endpoint and pbest unchanged. |
| O6 | **Paths are store-relative.** `dataset.path` is relative to the experiment directory (`output/rho.npy`). Content is served by joining it onto the mount behind a containment check (the zip-slip guard `ext.extract` already uses), rejecting `..` and symlinks that leave the directory. | No host paths or URLs in the API, so the store can move without rewriting rows. |
| O7 | **Ownership lives on the simulation; permission is inherited.** `simulation` gains `owner_sub` (nullable, the Auth0 `sub`) and `visibility` (`public` / `private`). `hpcrun`, `run_event`, `run_span` and `dataset` carry **no** owner columns; they reach the simulation by foreign key. Legacy and anonymous simulations are `owner_sub = NULL`, `public`. | compose-api has one owning entity. One source of truth means nothing to keep in sync, and a dataset can never be readable when its simulation isn't. |
| O8 | **One authorization seam, in the path from the first PR.** A FastAPI dependency `readable_simulation(simulation_id, principal) -> Simulation` calls a policy function `can_read(principal, simulation)`. Every new route and the existing status and results routes go through it. Today the policy allows everything. Dataset ids are UUIDs; simulation ids stay integers. | When #192 lands, only the policy function and the owner stamping at submit change; no route has to be found and fixed. UUIDs keep a private dataset from being found by counting. Integer simulation ids are kept for pbest. |
| O9 | **Every new endpoint has a CLI command in the same PR.** | The standing rule in `CLAUDE.md`, enforced by the spec-coverage test in `tests/client/test_cli.py`. The client is regenerated with `make clients`; `make check-clients` catches drift. |

## Plan

### Endpoints (every read goes through O8)

| Route | Returns | CLI |
|---|---|---|
| `GET /results/simulation/events?simulation_id&after&limit&level&event&span_id` | `RunEventPage{trace_id, events, next}` | `compose-api events ID [--follow] [--level] [--event]` |
| `GET /results/simulation/trace?simulation_id[&format=tree\|chrome]` | the span tree, or Chrome Trace JSON for Perfetto | `compose-api trace ID [--chrome FILE]` |
| `GET /datasets?simulation_id&kind&q&limit&offset` | `DatasetPage` | `compose-api datasets list [--sim ID] [--kind]` |
| `GET /datasets/{uuid}` | `Dataset` | `compose-api datasets show UUID` |
| `GET /datasets/{uuid}/content` | the file, streamed, with `Range` support | `compose-api datasets get UUID [-o FILE]` |

`compose_api_client.ext` gains `events(id, after=)`, `iter_events(id, follow=)`, `trace(id)`, `datasets(...)` and
`download_dataset(uuid, dest)`. There is no ingest endpoint: jobs never call the API.

### Schema (one Alembic revision, run at startup)

- `simulation`: `+ owner_sub text NULL`, `+ visibility text NOT NULL DEFAULT 'public'`.
- `hpcrun`: `+ trace_id char(32) NULL` (indexed), `+ events_cursor jsonb NOT NULL DEFAULT '{}'`,
  `+ last_event_at timestamptz NULL`, `+ exit_code int NULL`.
- `run_event`: `id`, `hpcrun_id` FK, `trace_id`, `source`, `seq`, `ts`, `component`, `event`, `level`,
  `global_time`, `wall_time`, `span_id`, `parent_span_id`, `payload` jsonb, `tags` jsonb;
  `UNIQUE(trace_id, source, seq)`, `INDEX(hpcrun_id, id)`.
- `run_span`: `id`, `hpcrun_id` FK, `trace_id`, `span_id`, `parent_span_id`, `name`, `attrs` jsonb, `start_ts`,
  `end_ts`, `duration_s`, `status`, `error`; `UNIQUE(trace_id, span_id)`.
- `dataset`: `id uuid`, `simulation_id` FK NOT NULL, `hpcrun_id` FK, `path`, `kind`, `media_type`, `display_name`,
  `size_bytes`, `sha256`, `attributes` jsonb, `origin` (`manifest` / `event`), `span_id`, `available`, `created_at`,
  `updated_at`; `UNIQUE(simulation_id, path)`.

Startup runs `upgrade_db` again (`dependencies.py:165`), so columns land with the deploy, and the k8s migration Job
moves from `poetry run` to `uv run`.

### Step 1: identity and the authorization seam
- O1: mint the correlation id before submission; the new `hpcrun` columns; the Alembic revision; `upgrade_db` at
  startup.
- O7/O8: the `simulation` columns, `readable_simulation` and `can_read`, applied to the existing status and results
  routes. Tests with the allow-all policy and with a test policy that denies (fails closed).
- *(Moved to step 1b, because it removes a k8s deployment and a public NodePort.)* Remove the NATS subscriber and
  settings. Leave the `worker_event` table one release, then drop it.
- *(Found building it.)* Startup ran `create_all` and a blind `stamp head`, which would have marked a database that
  alembic never tracked as already migrated, skipping the new columns. `create_db` now stamps an untracked database
  that already has tables at the pre-tracking baseline (`eb3903fb35a7`), then upgrades. Revisions are idempotent.
  `alembic/env.py` no longer reconfigures logging when the application runs it, which is the likely reason the startup
  upgrade had been commented out.
- *(Decided building it.)* A simulation the caller may not read answers 404, like one that does not exist, so ids
  reveal nothing. The admin role is named `admin` (`compose_api.authorization.ADMIN_ROLE`); see open question 7.

### Step 1b: retire NATS
- Removed: the subscriber and `get_hpcrun_by_correlation_id`, the `hpc_has_messaging` / `nats_*` settings, the client
  connection at startup, the `nats` k8s deployment and its NodePort 30052 service (base and both overlays), the
  `NATS_*` lines in `shared.env`, the `nats-py` and `async-lru` dependencies, and the NATS test fixtures and tests.
- Kept for one release: the `worker_event` table, its ORM class and the two `HPCDatabaseService` methods, so a deploy
  drops nothing. A later revision drops the table.
- **On deploy:** `kubectl apply` doesn't prune, so the running NATS objects must be deleted by hand:
  `kubectl -n compose-api-rke delete deployment/nats service/nats`.

### Step 2: events
- Job script: `--env PBG_*`, the `emit` helper with `trap … EXIT`, an `events/` directory.
- API events from `_dispatch_job` and from `JobMonitor` transitions.
- `compose_api/observability/`: the ported parsing, span folding, span tree and Chrome Trace renderer; the ingester
  and its tick.
- `run_event` / `run_span`; the events and trace routes; `ext`; CLI; `docs/cli.md`.

*(Found or decided building step 2.)*
- **The trace routes are two operations:** `/results/simulation/trace` (the span tree) and
  `/results/simulation/trace/chrome` (the Perfetto document), so each has one response type in the generated client.
- **The page field is `next_cursor`, not `next`.** The generator renames `next` to `next_`.
- **Events are returned in the order they were recorded** (by row id, which is what a cursor pages on), not by `ts`.
  Within one source that is the source's own order.
- **The ingester's terminal grace is kept in `events_cursor`** (`__terminal_seen__`, then `__done__`), so it uses no
  cluster clock and needs no extra column.
- **The env file, not `--env`.** `singularity --env` splits its value on commas, and `PBG_TRACE_BAGGAGE` has them.
- **The API's events use a microsecond timestamp as `seq`** (unique within the `api` source), so `run_event.seq` is
  BIGINT.
- **The job script traps SIGTERM** (`exit 143`), so a time limit or `scancel` still records `job.end` and closes the
  job span. A `SIGKILL` (the out-of-memory killer) cannot be trapped; the ingester closes that span as `unknown`.

### Step 3: datasets
- Job script: keep `output/`, write `artifacts.jsonl` before the zip.
- The manifest and `artifact.written` registrar, with event precedence; mark rows `available = false` when the file
  is gone.
- The `dataset` table and routes; content streaming behind the containment check; `ext`; CLI; docs.

*(Decided building step 3.)*
- **Q3, retention: keep `output/` and `results.zip` both** (Jim, 2026-10-07).
- **Q4, checksums: always.**
- **The manifest is events, not a separate `artifacts.jsonl`.** The job script emits one `artifact.written` per file
  (component `compose_api.job`) into `events/job.jsonl`, so the manifest and a simulator's own announcements take one
  path through the ingester. "Origin" is the component: `compose_api.job` is the manifest, anything else is an event.
- **`results.zip` is a dataset too** (kind `archive`), and a failed run's partial outputs are announced as well.
- **A dataset is registered before the ingester saves its cursor**, so a failed registration is retried on the next
  pass.
- **Routes:** `GET /datasets` (filters `simulation_id`, `kind`, `q`, `available`; `limit`/`offset`, with `total` and
  `next_offset`), `GET /datasets/{id}` and `GET /datasets/{id}/content` (Starlette's `FileResponse`, so `Range` works).
  A file that is gone answers 404 and marks the row `available = false`.
- **Listings apply the policy in SQL** (`authorization.readable_clause`), so a page never holds rows the caller can't
  see and `total` counts only readable ones.

### Step 4: a producer that emits (viva-pde-particle)
The ensemble entry point (`viva_pde_particle.benchmarks.fokker_planck:trial_rho`, run through
`compose_client.EnsembleRun`) emits `artifact.written` for each result file and runs inside a `task` span. This proves
the event feeder end to end against a real image.

### Step 5: auth (after #192)
Stamp `owner_sub` from the principal at `POST /simulation/run`; `can_read` becomes owner, or public, or an admin role;
`visibility` on submit and a `PATCH` to change it. This touches #192 only through its `OptionalPrincipal`.

## Verification

- **Unit tests, no SLURM.** Fixtures recorded in this repository from a real viva-pde-particle run's event stream,
  plus hand-written edge cases:
  - the ingester: partial lines, cursors, dedup, spans left open, debug filtering;
  - the registrar: an event wins over the manifest; vanished files become unavailable;
  - the content route rejects `..` and symlinks out of the experiment directory;
  - the authorization seam fails closed under a denying policy.
- **`tests-slurm` in CI.** An end-to-end run whose job script writes `events/job.jsonl` and `artifacts.jsonl`, and the
  API ingests both.
- **Live, after deploy, with viva-pde-particle:**
  1. `compose-api run x.omex --simulator viva-pde-particle --wait`
  2. `compose-api events ID` shows `dispatch.*`, `slurm.*`, `job.start`/`job.end`, and the engine's
     `run.start`/`run.end`.
  3. `compose-api trace ID --chrome t.json` opens in Perfetto.
  4. `compose-api datasets list --sim ID` lists the result files, and `datasets get` returns the same bytes as the
     zip.
- **A pbest image** (process-bigraph 1.0.5) still gets a trace from the API and job-script events, and datasets from
  the manifest.

## Risks

- **Concurrent appends on GPFS.** process-bigraph's file sink appends line by line; several processes writing one
  file on a network filesystem can interleave. Mitigation: one file per producer (`engine.jsonl`, `job.jsonl`) and
  open question 2.
- **Disk.** Keeping `output/` next to `results.zip` doubles a run's footprint. Open question 3.
- **Event volume.** A chatty image could write large streams. The ingester stores neither `tick` nor `debug`, reads a
  bounded number of bytes per tick, and the API's own events are few.
- **Migrations that start running.** Turning `upgrade_db` back on means a bad revision blocks startup. Mitigation: the
  revision is tested against a copy of the production schema before the deploy.

## Non-goals

- An OTLP exporter or an OpenTelemetry collector. The schema stays OTel-shaped so one can be added as another sink.
- Live streaming (websockets, server-sent events). `events --follow` polls.
- Dataset search across simulations by attribute or tag beyond `kind` and `q`; tags and attribute facets come if
  someone needs them.
- Per-dataset permissions. Datasets inherit their simulation's (O7).

## Open questions

1. ~~**Default visibility once auth lands**~~ *Decided 2026-10-07: private by default for a signed-in submitter (with
   a flag to make a simulation public); anonymous submissions stay public.* Step 5 implements it.
2. ~~**Several processes on one file sink**~~ *Decided 2026-10-07: upstream.* The production smoke run (sim 4334)
   had three engine processes appending to one `engine.jsonl` on GPFS. process-bigraph#229 lets a file sink's path
   name `{source}`, `{pid}` or `{host}`; the job script now asks for `engine-{source}.jsonl`, which older
   process-bigraph releases write as one literally named file, so nothing breaks before images pick it up.
3. ~~**Retention**~~ *Decided 2026-10-07: keep both `output/` and `results.zip`.* Revisit if cfs15 fills.
4. ~~**`sha256` in the manifest**~~ *Decided 2026-10-07: always.*
5. ~~**The SLURM `.out` log**~~ *Decided 2026-10-07: as a dataset.* A simulation job's log moves from `htclogs/`
   into its experiment directory as `job.out`, and the job script announces it as kind `log` (no size or checksum:
   SLURM writes after the trap). `compose-api datasets get` reads it. Container builds still log to `htclogs/`.
6. **Port or depend on viva-core?** Proposed: port the pure functions now, and depend on viva-core once it is
   published as its own package with a stable event and dataset API.
7. **Which role reads everything?** *Decided 2026-10-07: settle it with #192.* `admin` stays a placeholder in
   `compose_api/authorization.py` until the Auth0 tenant's role name is known.
8. ~~**Before the step-1 deploy**~~ *Done 2026-10-07 (prod was at `eb3903fb35a7`; migrated to `c41f0b7a9d20` on
   the 0.7.0 deploy).* check the production database's `alembic_version` (expected `eb3903fb35a7`, or no
   table at all). Either is handled, but a different value means someone migrated by hand.
