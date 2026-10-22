# Durable submission: runs queued as `requested`, dispatched by a worker, ready for fair scheduling

**Status (2026-10-11): proposed.** This follows #256 (0.7.9), which made a lost submission *fail* with a reason. This
plan makes it *resume* instead. It covers the rest of #238. **(2026-10-22: revised against `main` and accepted; see
[Revisions](#revisions-2026-10-22). Steps 1–4 are this round, one PR each, merged with a merge commit. Each needs a
release to deploy.)**

| Step | What | State |
|---|---|---|
| 1 | This document, revised | **done** #258 |
| 2 | Staging, the `submission` table, and the worker (Q1, Q2) | in review |
| 3 | Scheduling and caps (Q3); resumable suite runs and the batch profile for SED-ML runs (Q4) | — |
| 4 | Surface the submission (API, CLI, UI); retire #256's heartbeat and stale check | — |
| 5 | Then the 300-model BioModels suite | — |
| later | Registry `/build` endpoints through the queue; pulls as Kubernetes Jobs (former D4); per-owner fairness | — |

## Context

A simulation reaches SLURM in two stages (`compose_api/simulation/handlers.py`):

1. **API-side, in memory.** `POST /simulation/run` records the simulation and queues a FastAPI background task in
   the same process. The upload sits in a pod-local temporary file (`common/gateway/utils.py`). The task:
   - makes the image ready (`ensure_image`): a synchronous `singularity pull` over SSH, or a Kubernetes build Job that
     it waits on through the database;
   - then copies the input with `scp`, runs `sbatch`, and records the `HpcRun`.
2. **SLURM-side, durable.** After `sbatch`, SLURM queues the job. The monitor rebuilds its view from Postgres on every
   pass, so a restart loses nothing here.

Everything in stage 1 is lost when the process stops: the task, the uploaded file, and its place in line.
- **Before 0.7.9,** such a simulation stayed `submitting` forever. 51 production simulations did.
- **Since #256,** it fails with "resubmit". That is honest, but the user has to resubmit, and every deploy during a
  first run of a new image costs that run.

**Bulk submissions make it worse (2026-10-22).**
- A suite run (`sedml/suite_runs.py`) fetches and translates every source first. Only then does it dispatch all of its
  simulations, one after another, from one in-memory `BackgroundTasks`.
- #256's stale check fails any simulation that has had no dispatch heartbeat for 300 s. A simulation that has not
  started yet has none, so its creation time counts (`hpc_db.list_stale_submissions`).
- That is fine for a 20-model suite. With 300 models on two solvers, most of the 600 simulations would be failed as
  "abandoned" while still waiting for their turn.
- The suite's own loop is an untracked `asyncio.Task`, and the suite run is marked `submitted` before anything has been
  dispatched.

## Goal

- **Every accepted run is a durable `requested` row from the moment the request returns.** It either reaches SLURM
  exactly once, or ends FAILED with a reason. This holds across API restarts, deploys and replicas, with no manual
  resubmission.
- **No duplicate SLURM jobs,** even when the API dies between `sbatch` and recording the job id.
- **One worker decides what is dispatched next,** under caps and in priority order. This is where fair scheduling
  goes later.
- **Suite runs resume** from the source they had reached.

## Decisions (Jim, 2026-10-22)

- **`requested` is additive.** The public simulation `status` is unchanged: `submitting` until there is a run, then the
  run's status. pbest and the published clients need nothing. A new `submission` field on the simulation carries
  `requested`, `preparing` and `submitting`, and the queue position. The UI shows "requested (#N in queue)".
- **Steps 1–4 this round,** before the 300-model suite.

## Design

### Q1. Stage the input, then record a `submission` row in state `requested`

- **The request writes the input into the experiment directory on the shared store** before answering.
  - The API pod already mounts the store, at the same path the jobs use in production (`kustomize/base/api.yaml`).
  - The helper goes in `hpc_utils.py`, next to `get_internal_experiment_dir`.
  - SED-ML runs also stage `source.omex` there, instead of in a `mkdtemp` directory that is never removed.
- **In the same transaction as `insert_simulation`**, the request inserts the `submission` row and kicks the worker.
  It no longer schedules a background task.
- **The table** (`db/tables/hpc_tables.py`; `create_all` creates it. One idempotent revision adds its indexes and the
  backfill):

  | Column | Meaning |
  |---|---|
  | `simulation_id` (PK, FK) | one submission per simulation |
  | `state` | `requested`, `preparing`, `submitting`, `submitted`, `failed` |
  | `queue` | `interactive` by default; a suite run's simulations use `suite:<name>` |
  | `priority` | integer, default 0; suite runs use −10 |
  | `requested_by` | the caller's subject when signed in. Recorded for fairness, not ownership (observability step 5 is separate) |
  | `attempts`, `next_attempt_at`, `last_error` | retry bookkeeping (Q2) |
  | `lease_owner`, `lease_expires_at` | which worker holds the row, until when |
  | `created_at`, `updated_at` | |

- **The row also keeps what dispatch needs from the request.** Today that exists only in memory: the file type, end
  time, batch flag, prebuilt simulator, and the staged input and source paths. They are kept as `request` (JSONB), so
  the worker can rebuild the job after a restart.
- **Staging and file ownership.**
  - The API (uid 16997) writes the staged files world-readable under `<namespace>/staging/<experiment_id>/`, not into
    the experiment directory. The experiment directory stays the SLURM service user's, made by that user with
    `mkdir -p`, so the job can write its outputs and events there.
  - At dispatch, the worker copies the staged files into the experiment directory over SSH, a copy on the cluster
    itself rather than a transfer.
  - Where the store is not mounted (development, tests), staging falls back to a local directory
    (`submission_staging_dir`), and the worker uploads from it with `scp` as today.
- **Backfill:** every existing simulation with no run gets a `failed` row. #256 has already failed them.
- **Failures surface as today,** through the FAILED `HpcRun` with `slurmjobid = null` that #256 introduced
  (`hpc_db.fail_submission`).

### Q2. The worker: claim, lease, step

- `simulation/submission_worker.py` is started in the API's lifespan, next to `verify_images_periodically`, and
  stopped on shutdown. The request path wakes it through an `asyncio.Event`; otherwise it polls every 5 s.
- **Claim.** `SELECT … FOR UPDATE SKIP LOCKED` over the due rows, ordered by the scheduling policy (Q3). It sets
  `lease_owner` (the pod name plus a uuid) and `lease_expires_at` (about 2 min), and renews the lease while it works.
- **A lost worker is just an expired lease.** The next pass, on any replica, claims the row again and resumes from its
  `state`. This replaces #256's heartbeat and stale check, which step 4 removes.
- **Each step is short and commits its own state change.**

  | From | To | What |
  |---|---|---|
  | `requested` | `preparing` | claimed for dispatch, within the caps (Q3) |
  | `preparing` | `submitting` | `ensure_image`, unchanged. It already finds a recorded image (`environment_image`) and joins an in-flight build, so rows on the same hash wait on one image |
  | `submitting` | `submitted` | idempotent `sbatch` (below), then the `HpcRun` and the state, in one transaction |

- **Idempotent `sbatch`.** The SLURM job name is the simulation's `experiment_id`. Before submitting, the step looks
  the job up: `squeue --name=<experiment_id>`, then `sacct --name -X` for a finished one. If it finds a job, it adopts
  it instead of submitting again. The experiment directory is made with `mkdir -p`, and the input is already staged,
  so `submit_job` no longer copies it.
- **Retries.**
  - **Transient errors** are retried with backoff (30 s, 1, 2, 4, 8 min), up to `submission_max_attempts` (default 6),
    recording `last_error`. Transient means SSH, a busy scheduler, or the file system.
  - **Permanent errors** fail at once: a missing staged input, an invalid partition or QoS, a failed build.
  - **`submission_timeout_seconds`** stays an overall deadline from `created_at`.

### Q3. Scheduling: the seam for fair scheduling

- **A policy object chooses which claimed rows to dispatch:** `SubmissionPolicy.select(candidates, active)` in
  `simulation/scheduling.py`.
  - The first policy is priority, then age, under caps.
  - Round-robin across queues, or fair share per requester, can replace it later without a schema change: the
    `queue`, `priority` and `requested_by` columns exist from Q1.
- **Caps, counted from the database:**

  | Setting | Caps | Default |
  |---|---|---|
  | `submission_max_active_jobs` | simulation runs on SLURM that have not finished | 200; set it below the `vcell-services` QoS limits once they are checked |
  | `submission_max_preparing` | concurrent image fetches and builds | 4 |
  | `submission_queue_share` | the fraction of the active cap one non-interactive queue may use | 0.5, so interactive runs are never starved |

- **The effect:** a 600-run suite drains at a steady rate behind interactive work, instead of 600 `sbatch` calls in a
  burst.

### Q4. Suite runs that resume

- **The `suite_run` row records its progress:** `sources` (the list, JSONB) and `next_source`. One idempotent revision.
- **Each source is idempotent.** A source whose comparisons already exist for `(collection, suite_run, source)` is
  skipped. Otherwise: fetch → translate → `service.submit` (which enqueues `requested` rows) → `next_source += 1`.
- **The worker also claims suite runs in `submitting`** (with `SKIP LOCKED` and a lease) and continues from
  `next_source`. A suite run becomes `submitted` only after its last source.
- **Queue and priority.** A suite run's simulations use `queue = suite:<name>` and priority −10.
- **The batch resource profile.** SED-ML runs (ODE models, seconds of work) use 1 CPU and 1 GB. Today
  `sedml/service.py` hard-codes the interactive profile (2 CPUs, 8 GB).

## Steps

1. **This document, revised.**
2. **Staging, table and worker** (Q1, Q2).
   - The request path enqueues and the worker dispatches.
   - #256's stale check stays as a safety net until step 4.
   - Tests:
     - claim with `SKIP LOCKED` across two workers;
     - resume from every state after an expired lease;
     - retry, then permanent failure;
     - `sbatch` adoption by job name on the SLURM test cluster (`slurm` marker);
     - the `--name` output shapes in `tests/common/test_slurm_conformance.py`.
3. **Scheduling and suites** (Q3, Q4).
   - Tests:
     - the caps hold;
     - interactive runs go ahead of suite runs;
     - a resumed suite run neither repeats nor skips a source.
4. **Surface and retire.**
   - `submission: {state, queue, position, attempts, last_error}` on `SimulationSummary` and `SimulationDetail`.
   - The CLI and the UI show it.
   - `make clients` regenerates the spec and the client.
   - Remove `supervise_dispatch`, `fail_stale_submissions` and `simulation.dispatch_heartbeat_at`, with a revision that
     drops the column.
5. **The 300-model suite:** a generator script, and `examples/biomodels-curated-300/suite.yaml`. It runs once the QoS
   limits are known.

## Verification

- **Kill test** (after step 2, on production, deliberately):
  1. Start a 20-model suite run.
  2. `kubectl rollout restart deploy/api` while it is submitting.
  3. Every run must complete, and `sacct --name=<experiment_id>` must show exactly one job per run.
- **Loki:**
  - no `Submission abandoned` lines after step 2;
  - resumed work logs `claimed … resuming from <state>`.
- **The 300-model suite:**
  - the count of active jobs stays at or under the cap;
  - an interactive run submitted mid-suite starts at once;
  - the suite page shows `requested (#N)` draining.

## Revisions (2026-10-22)

The 2026-10-11 draft predates environment-builds phases 1–4. Against `main`:

1. **Builds are Kubernetes Jobs in production** (`BUILD_BACKEND=k8s`). They are waited on by polling the database
   (`builds.wait_for_run`), so any process can join one.
   - The in-memory listeners and the 30-minute cap the draft wanted to remove apply only to the SLURM build backend.
   - The draft's D4 ("pull and build as SLURM jobs") is therefore narrowed to *pulls* as Kubernetes Jobs, and deferred
     to "later".
2. **Image readiness is the `environment_image` record plus a file check through the mount**, not an SSH `test -s`.
   The worker calls `ensure_image` unchanged.
3. **Deduplication:** joining an in-flight build exists already. The advisory lock still spans the whole pull or
   build, which is acceptable for now because Q3 caps concurrent preparation.
4. **The draft's `accepted` state is named `requested`** (Jim). The draft's `fetching` and `building` collapse into
   `preparing`, because `ensure_image` owns both.
5. **New in this revision:**
   - scheduling (Q3): the queue, priority and requester columns, and caps;
   - resumable suite runs and the batch profile (Q4);
   - the request-time staging of SED-ML archives.
6. **Still open:** the registry's `/build` endpoints also run `ensure_image` as in-process background tasks, which a
   restart loses. They move onto the queue later.

## Open questions

1. **The `vcell-services` QoS limits** (`sacctmgr show qos vcell-services`). They set `submission_max_active_jobs`.
2. **Replicas.** The production overlay runs one API replica; the base sets three. The worker is written for several,
   and step 2's claim test runs two workers against one database.
3. **Fairness per requester:** owners are not stamped yet (observability step 5). `requested_by` keeps the subject for
   when a fair-share policy needs it.
