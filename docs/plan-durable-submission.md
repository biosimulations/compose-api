# Durable submission: a queue that survives API restarts

**Status (2026-10-11): proposed.** This follows #256 (0.7.9), which made a lost submission *fail* with a reason. This
plan makes it *resume* instead. It covers the rest of #238. One PR per step, each merged on green with a merge commit.
Deploying is a separate go from Jim.

| Step | What | State |
|---|---|---|
| 0 | This document | proposed |
| 1 | Stage the input on the shared store in the request; a `submission` row per simulation | — |
| 2 | Submission worker: claim, lease, step, retry; drives `sbatch` idempotently | — |
| 3 | Container fetch and build as SLURM jobs that the worker waits on through the monitor | — |
| 4 | Surface the submission state (API, CLI, UI); retire #256's heartbeat | — |

## Context

A simulation gets to SLURM in two stages (see the answer on #238 and `compose_api/simulation/handlers.py`):

1. **API-side, in memory.** `POST /simulation/run` records the simulation, then starts a FastAPI background task in
   the same process. The task:
   - fetches the container image over SSH (`singularity pull` on the submit host);
   - or, if that fails, builds it as a SLURM job and waits up to about 30 min through in-memory queues
     (`JobMonitor.internal_listeners`);
   - then runs `sbatch` and records the `HpcRun`.

   The uploaded file sits in a temporary directory on the pod.
2. **SLURM-side, durable.** After `sbatch`, SLURM queues the job (`PENDING` until a node is free). The monitor rebuilds
   its view from Postgres on every pass, so a restart loses nothing.

Everything in stage 1 is lost when the process stops: the task, the uploaded file, and the build wait. Each step has no
queue and no retry, so it either succeeds once or the submission ends.
- **Before 0.7.9,** such a simulation stayed `submitting` forever. 51 production simulations did.
- **Since #256,** it fails with "resubmit". That is honest, but the user still has to resubmit, and every deploy
  during a first run of a new image costs that run.

## Goal

- **Every accepted submission either reaches SLURM exactly once, or ends FAILED with a reason.** This holds across API
  restarts, deploys and replicas, with no manual resubmission.
- **No duplicate SLURM jobs,** even when the API dies between `sbatch` and recording its job id.
- **No long work held by a process.** Anything that takes minutes runs as a SLURM job. The API only takes short,
  idempotent steps it can repeat.

## Design

### D1. Stage the input durably before answering

- The request writes the upload into the experiment directory on the shared store. The API pod already mounts it at
  `/projects/CRBM`; the ingester reads `events/` and datasets from there. Today the file stays in a pod-local temp
  directory until the background task copies it with `scp`.
- Path helpers go in `hpc_utils.py`, next to `get_slurm_sim_input_file_path`: the internal (mounted) view of the same
  file.
- The response is sent only once the file is on the store and the `submission` row is committed (D2). A request that
  fails before that has created nothing.
- **Why the store,** compared with the alternatives:
  - It is where the job reads the file anyway.
  - Uploads are at most a few MB, so a synchronous write adds little latency.
  - Postgres `bytea` would duplicate the file and grow the database.
  - A synchronous `scp` in the request would put SSH in the request path.

### D2. A `submission` table: one row per simulation, a small state machine

```
accepted ──► fetching ──► (building) ──► submitting ──► submitted
    │            │             │              │
    └────────────┴─────────────┴──────────────┴──► failed (reason)
```

| Column | Meaning |
|---|---|
| `simulation_id` (PK, FK) | one submission per simulation |
| `state` | `accepted`, `fetching`, `building`, `submitting`, `submitted`, `failed` |
| `attempts`, `next_attempt_at` | retry bookkeeping (D5) |
| `lease_owner`, `lease_expires_at` | which worker holds it, until when (D3) |
| `build_hpcrun_id` | the container build this submission waits on (D4), if any |
| `last_error` | the most recent failure, kept across retries |
| `created_at`, `updated_at` | |

- **Public status is unchanged:**
  - `submitting` while there is no `HpcRun` and the state is not `failed`;
  - `failed`, with the reason, through the same FAILED `HpcRun` that #256 introduced (`slurmjobid = null`);
  - after `sbatch`, the existing `HpcRun` as today.

  So pbest and the published clients need nothing new.
- **Migration:** an alembic revision creates the table (idempotent).
- **Backfill:** every existing simulation with no run gets a `failed` row. They have already been failed by #256, so
  this changes nothing.

### D3. The submission worker: claim, lease, step

- A `SubmissionWorker` runs in the API process, on the job monitor's loop or as a sibling task started in the lifespan.
  On each pass it claims due rows:

  ```sql
  SELECT simulation_id FROM submission
  WHERE state IN ('accepted','fetching','building','submitting')
    AND next_attempt_at <= now()
    AND (lease_expires_at IS NULL OR lease_expires_at < now())
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT :batch
  ```
- It sets `lease_owner` (pod name plus a uuid) and `lease_expires_at = now() + lease` (e.g. 2 min), then commits.
  While working, it renews the lease.
- **A lost worker is just an expired lease.** The next pass on any replica claims the row again and resumes from its
  `state`. This replaces #256's heartbeat and stale check: an expired lease resumes the submission instead of failing
  it.
- **Each step is short and moves the state forward in its own transaction.** Long work never runs inside a step:
  it is a SLURM job the step starts or checks (D4). The request handler also kicks the worker (an `asyncio.Event`),
  so a submission starts at once rather than on the next pass.
- **Shutdown:** on SIGTERM the worker stops claiming and lets its leases expire. The new pod picks the rows up.

### D4. Container fetch and build become SLURM jobs

- Today `singularity pull` runs synchronously over SSH: minutes, held by the API process. If the API dies mid-pull,
  the remote command may be killed with the SSH channel. Also, a build waits through in-memory queues and gives up
  after about 30 minutes even if the build later succeeds.
- **`fetching`:** if the `.sif` exists (`test -s`), skip to `submitting`. Otherwise submit a small **pull job**: the
  same `test -s || pull to tmp && mv` script, run as `sbatch` on the build partition. Record it as a
  `BUILD_CONTAINER` `HpcRun` and move to `building`.
- **`building`:** the monitor already polls that `HpcRun`. When it completes, move to `submitting`.
  - If the pull fails, fall back to a build job, as today.
  - If the build fails, mark the submission `failed` with the build log's tail.

  There is no in-memory wait and no 30-minute cap; the build's own SLURM time limit governs.
- **Deduplication across submissions:** the per-hash advisory lock stays, but it is held only for the short step of
  *finding or creating* the hash's pull/build `HpcRun`. Submissions on the same hash all point
  `build_hpcrun_id` at that one run.

### D5. Idempotent `sbatch`

- The SLURM job name is already the `experiment_id`, which is unique per simulation. Before calling `sbatch`, the step
  in `submitting` looks the job up by name: `squeue --name=<experiment_id> --noheader -o %i`, then
  `sacct --name=... -X` for a job that has already finished.
- If it finds one, it **adopts** that job id instead of submitting again. That covers a worker that died between
  `sbatch` and the insert.
- Otherwise it runs `sbatch`. In the same transaction as the move to `submitted`, it inserts the `HpcRun`, sets the
  state, and clears the lease.
- **Test:** `tests/common/test_slurm_conformance.py` gains the `--name` output shape on both backends.

### D6. Retries, the deadline and failure reasons

- **Transient errors are retried** with exponential backoff (30 s, 1, 2, 4, 8 min), up to `submission_max_attempts`
  (default 6). Each attempt records `last_error`. Transient means an SSH connection error, `sbatch` exiting non-zero
  with a scheduler-busy message, or an NFS error writing the script.
- **Permanent errors fail at once:** a missing staged input, an invalid partition or QoS, or a container build that
  failed.
- **`submission_timeout_seconds`** stays as an overall deadline from `created_at`, as in #256. A submission still not
  submitted by then fails with "did not reach SLURM within …".
- Failure reasons go to the FAILED `HpcRun`'s `error_message`, so every existing consumer shows them.

### D7. Backpressure (optional, step 2)

- `submission_max_in_flight` (default unlimited) caps how many submissions are in `fetching` or `building` at once.
- Claimed rows past the cap get `next_attempt_at` pushed out.
- This replaces today's behaviour, where 50 simultaneous first runs each start a task and all block on the same
  advisory lock.

## Steps

1. **Staging and the table.**
   - D1 and D2.
   - The request handler stages the file and inserts the `submission` row; it still starts today's background task
     unchanged.
   - Migration and backfill.
   - Tests: the staged file exists before the response; a failed write creates nothing.
2. **The worker.**
   - D3, D5, D6, D7.
   - The handler stops starting a background task; it inserts the row and kicks the worker.
   - Fetch and build still use today's `_download_or_build_container`, inside a step with lease renewal: a pull
     interrupted mid-way is repeated, which is safe because it is idempotent.
   - #256's stale check becomes lease expiry.
   - Tests:
     - claim with `SKIP LOCKED` across two workers;
     - resume after an expired lease in every state;
     - `sbatch` adoption by job name against the SLURM test cluster (`slurm` marker);
     - retry, then permanent failure.
3. **Fetch and build as SLURM jobs.**
   - D4.
   - Removes the in-memory build wait (`internal_listeners` for builds) and the 30-minute cap.
   - Tests: a pull job and a build job on the test cluster (`test_container_lifecycle.py` already builds there), and a
     restart while `building` resumes when the build completes.
4. **Surface and retire.**
   - `SimulationDetail` gains `submission: {state, attempts, last_error}`; the CLI shows it; the UI shows the state
     while `submitting`.
   - Remove `simulation.dispatch_heartbeat_at` and `supervise_dispatch` once no code path uses them (a revision drops
     the column).

## Verification

- **Kill test** (step 2, staging or production):
  1. Submit a first run of a new simulator image.
  2. `kubectl rollout restart deploy/api` during the pull.
  3. The run must reach `completed` with no second SLURM job: check `sacct --name=<experiment_id>` for exactly one
     job.
- **Loki:** no `Submission abandoned` lines after step 2. Resumed submissions log `claimed … resuming from <state>`.
- **Deploy during a busy period:** every run either completes or fails with a specific reason, never "abandoned".

## Open questions

1. **Pull on a compute node versus the submit host.** Step 3 assumes compute nodes can reach the registry, which the
   build job already needs. Confirm with the HPC admins that the build partition is right for pulls too.
2. **Staged-input retention.** The experiment directory already keeps the input. Nothing new to clean up unless a
   submission fails before its directory is used; such a directory then holds only the input.
3. **Replicas.** Production runs one API replica. The design does not depend on it, but the conformance and resume
   tests should run two workers against one database to prove it.
4. **Batch submissions** (pbest `batch_submission=True`) arrive as many requests at once. D7's cap and FIFO order
   should keep them from starving single runs. Is per-owner fairness needed once owners are stamped (observability
   step 5)?
