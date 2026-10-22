# Plan: vivarium-workbench on compose-api (retiring viva-api)

## Context

Goal: `cd <workspace> && uv run vivarium-workbench serve --backend-base-url https://compose.cam.uchc.edu/`, then run
and dispatch as normal, with compose-api as the backend in place of viva-api, which is being archived. compose-api
goal **G7** (one execution backend) names this convergence.

Decisions already made by Alex (2026-10-22):
1. **Workspace code runs via owner-published images first.** Each workspace image is listed by digest in
   `PREBUILT_SIMULATORS`. Per-run repo install comes as a second compose-api phase, and **jcschaff reviews that
   choice before it is built**.
2. **PRs to vivarium-workbench are in scope**, overriding strategy.md's "vivarium-collective is read-only".
3. **compose-api becomes the default backend.** The viva-api code stays in place, inert. A removal plan for the
   SMS-only flows is written now and executed only when Alex asks.

## Verified findings that shape the plan

All read from the source or the live deployment (0.7.33), not from summaries.

- **The workbench already has a backend seam.** `server_capabilities.backend_profile` picks a dispatch mode
  (`legacy` or `viva-v1-document`). `remote_run_viva_v1.py` (303 lines: `submit` / `land` / `status` / `progress` /
  `cancel`) is the adapter to mirror. `--backend-base-url` sets `VIVARIUM_WORKBENCH_BACKEND_BASE_URL`, read in
  `sms_api_client.py:24-74`.
- **viva-api's `/compose/v1` is a fork of compose-api's submit, status and results flow.** compose-api's equivalent
  is simpler: `run-simulation` returns `simulation_database_id` directly, so the workbench's correlation-id
  reverse lookup (`remote_run.compose_simulation_id`) is unnecessary.
- **Hard incompatibilities:**
  - `pbg_export` writes `local:!<module>.<qualname>`, which compose-api always refuses (`registry/validation.py`).
    Accepted form: `local:<module>.<Class>`.
  - Landing (`remote_run_landing.land_composite_results`) requires `emitter_history.json`. compose-api runners
    (pbest, viva-pde-particle's `compose_runner`) write `results_<date>.pber`, which holds `gather_emitter_results`
    as JSON.
  - compose-api has **no cancel endpoint** and **no capabilities route**.
  - viva-api's per-run `extra_pip_deps` (`git+origin@HEAD`) has no compose-api counterpart. That gap is Phase 3.
- **Pilot needs no compose-api change.** viva-pde-particle is a workbench workspace (`workspace.yaml`) and is
  already a `tested` registry entry with its own prebuilt image (`?simulator=viva-pde-particle`).
- **The runner can't be pbest.** pbest pins process-bigraph 1.0.5; workspaces need ≥1.9. viva-pde-particle wrote
  its own runner for this reason and deliberately keeps vivarium-workbench out of its image. A shared runner for
  other workspaces therefore needs a small home of its own. That is an item for Jim's review.
- **The client isn't published.** PyPI `compose-api-client` is stuck at 0.7.6, and there have been no GitHub
  releases since 0.5.0 (tags only), so `publish-client.yml` never fired. This violates BOJ tenet 2, and the
  workbench can't depend on a current typed client until it's fixed.
- **Env workers don't block a laptop `serve`.** They are local unless `ENV_WORKER_PROXY_BASE` or
  `ENV_WORKER_ADVERTISE_HOST` is set (`env_worker_launcher.default_launcher`).
- **Run ids collide.** The workbench routes a run by the shape of its id: `remote_run_viva_v1.is_run_id` treats a
  non-digit string as a `/viva/v1` id and digits as a legacy SMS id. compose-api's `simulation_database_id` is an
  int, so the compose mode carries `compose-<id>` and is checked before both. A pending row stays unambiguous even
  if the operator switches backend.
- **For a prebuilt run, the workbench preflight is the only class check.** `run-simulation` with `simulator=` calls
  `validate_submission(..., registry=False)`: it refuses `local:!` and other protocols but does not look classes up.
  The manifest check in Phase 1 is therefore a safety gate, not a convenience.
- **A `.pber` already has landing's shape.** It is `{<emitter path>: [state per step]}` at the root of `results.zip`
  (`job_script.py` zips `output/`), which is the one-emitter rule `emitter_history.json` follows. Landing gains a
  second reader, not a new mapping.
- **The client already holds a session.** `compose_api_client.auth.sources.SyncStoredSession` reuses a
  `compose-api login`, so the workbench gets a bearer token for cancel without auth code of its own.
- **No alembic revision for cancel.** `JobStatus.CANCELLED` exists in the model and the DB enum, and `JobMonitor`
  already maps SLURM's `CANCELLED`.

## Phase 0: loop in Jim, unblock the client (compose-api)

0a. **Jim review.** Draft a GitHub issue on `biosimulations/compose-api` @-mentioning `jcschaff`. It covers the
    phased code path (images now, per-run install later), the trust-model implication for G6, where the shared
    runner should live, and cancel authorization (0c). **Show the draft to Alex before posting** (outward-facing).
    Phase 3 is gated on Jim's answer.

0b. **Release.** A GitHub Release for a tag triggers `publish-client.yml`, which publishes `compose-api-client` at
    the service version. The release PR carrying 0c is prepared and left open; **when to publish is a question for
    Jim** (0a). Going forward, every `make tag` is followed by a release.

0c. **Cancel endpoint** (one PR; BOJ 1 and 6):
    - `DELETE /simulations/{simulation_id}` with `operation_id="cancel-simulation"`. It runs `scancel` through
      `SlurmService` and records `JobStatus.CANCELLED`. A queued `submission` row is withdrawn before any sbatch
      (`simulation/submission_worker.py`).
    - Authorization (Alex, 2026-10-22; for Jim's review): a 401 when anonymous, and any signed-in principal while
      no simulation has an owner. Once owners are stamped, owner or `admin_role` only.
    - Also in the same PR: a CLI command (`@claims`, or `tests/client/test_cli.py` fails), `make clients`, and `@pytest.mark.slurm` tests on the `slurm_backend` fixture.
    - Then a release (0b) so the client carries it.

## Phase 1: the workbench speaks compose-api (vivarium-workbench PR, pilot viva-pde-particle)

New dispatch mode `compose-api`, behind the existing seam. Representative files:

| Change | Where |
|---|---|
| **Detect** the backend from `GET /openapi.json`: the mode is `compose-api` when the operations `run-simulation`, `get-simulation-status`, `get-simulation-results-file` and `list-environments` are present. These operation ids are compose-api's stable public contract (pbest relies on them). The check is membership, never version, as `server_capabilities` already does. | `lib/server_capabilities.py` (`DISPATCH_COMPOSE`, `backend_profile`) |
| **Adapter** mirroring `remote_run_viva_v1.py`:<br>• `submit`: export → `run-simulation(uploaded_file=.pbg, interval_time, simulator, tags=[workbench, study], description)`<br>• `status`: `get-simulation-status`<br>• `land`: `get-simulation-results-file`<br>• `progress`: status plus `get-simulation-events`<br>• `cancel`: `cancel-simulation` (0c)<br>• trace: `get-simulation-trace-chrome`, so "Open in Perfetto" works<br>Uses the generated **`compose-api-client`** (a new dependency, light: httpx and attrs), not more hand-written urllib. | new `lib/remote_run_compose.py`; dependency in `pyproject.toml` |
| **Environment resolution:**<br>• The workspace's git origin is matched to an entry's `source` in `GET /registry/entries`; that entry's prebuilt bundle supplies the `simulator=` value.<br>• Override with the existing `VIVARIUM_WORKBENCH_BACKEND_ENVIRONMENT=name:<env>`.<br>• No match is a clear 409 that names the registration steps (Phase 2). | `lib/remote_run.py` (`backend_environment`) |
| **Preflight against the live manifest:**<br>• Every address in the exported document must be in `GET /registry/environments/{name}/manifest`. A refusal names the missing class, in place of compose-api's 400.<br>• Warn when the workspace HEAD differs from the entry's pinned `commit`; provenance records the image digest and entry commit. | `lib/remote_run.py` (`remote_dispatch_preflight`) |
| **Address form:** an option for `local:<module>.<qualname>` (no `!`), used by the compose mode. | `lib/pbg_export.py` |
| **Landing:** read `results_*.pber` beside `emitter_history.json`, with the same one-emitter rule and the same `history` rows. | `lib/remote_run_landing.py` |
| **Routing:** where `uses_viva_v1_dispatch` branches, add the compose mode: study baseline and variant, composite card, `/api/remote-run-{submit,poll,land,cancel,chain-progress,trace}`, and `/api/remote-run-config` reporting `dispatch: compose-api`. | `lib/remote_pinned.py`, `lib/study_runs.py`, `lib/remote_run_views.py`, `lib/composite_test_run_views.py`, `lib/remote_trace.py` |
| **Default:** a named backend that answers as compose-api takes compose mode. With no backend named, `serve` keeps running locally, unchanged. viva-api code paths stay but are only reached when the backend advertises `/viva/v1`. | `lib/server_capabilities.py` |
| **Docs:** a `docs/backend-compose-api.md` matching `backend-viva-v1.md`'s provenance table, plus a pointer from the README. | docs |

Tests follow the workbench's own pattern: commit the live spec as `tests/_contracts/compose_api_openapi_<ver>.json`
and generate the stub routes from it, like `tests/_viva_v1_stub.py`. Per the anti-mock rule, the stub covers only
the transport. Address form, preflight and landing are tested against a real exported workspace document and a real
`.pber` produced by the real runner (`python -m viva_pde_particle.compose_runner smoke`). The contract test fails
when the snapshot drifts.

## Phase 2: onboarding any workspace (images)

For workspace W, per pattern (no new mechanism):
- **W's repo:** a `compose.Dockerfile`, an image-publishing workflow, and a runner. Template them in `viva-template`
  from viva-pde-particle's `compose-image.yml` and `docker/compose-entrypoint.sh`, including its apptainer `--compat`
  contract check before the push. The generic runner's home comes from Jim's answer (0a).
- **compose-api, one config PR:**
  - a `manifest.yaml` entry (`tested`, `bundles: [W]`, `commit`, evidence);
  - an `environments.yaml` entry;
  - the digest in `PREBUILT_SIMULATORS` (`kustomize/config/compose-api-rke/api.env`);
  - CI-regenerated `registry/manifests/W.json`;
  - a deploy tag (BOJ 2).

## Phase 3: per-run repo install (compose-api; gated on Jim, 0a)

Sketch only, to be revised after review:
- `run-simulation` gains a source (`git+<repo>@<sha>`) whose repo must be on a reviewed allow-list. The candidate
  allow-list is `catalog.yaml` / `manifest.yaml`, which is viva-api#975's goal, already met here.
- The environment definition (base runner image plus that install) is hashed through the existing identity path:
  def-file md5 → `SimulatorVersion` → build once, reuse.
- The G6 trust change is recorded as a dated strategy decision.
- The workbench then sends `repo@HEAD` (the clean-and-pushed preflight already exists) in place of `simulator=`.

## Phase 4 (written now, executed only on request): remove viva-api from the workbench

1. Delete the dispatch modes `legacy` and `viva-v1-document`: `remote_run_viva_v1.py`, the `/viva/v1` and
   `/compose/v1` parts of `sms_api_client.py`, and the `resolve_path` spellings.
2. Delete the SMS-only flows, with their routes, JS and tests:
   - pinned build (`remote_pinned`, `/api/remote-run-pinned-build`, `_dispatchRemotePinned`);
   - switch-build and the branch picker (`source_build_views`, `remote_build_source`, `branch-source.js`);
   - `/api/v1/analyses*` and S3 figures (`remote_analysis_figures`, `fold_analyses`, `land_ptools_tsvs`);
   - chain campaigns;
   - image-backed composite-resolve;
   - the dead `comparison_pinning.py`;
   - remote env-worker launchers (`Proxy` and `Remote`, leaving the local launcher);
   - the `VIVA_API_BASE` / `SMS_API_BASE` aliases.
3. Rename `SmsApiClient` and `sms_api_base` callers to the compose client, and remove `smsvpctest` defaults.
4. Precondition: confirm with the SMS ecosystem's owners that nothing there still needs these flows.

## Verification

- **0c:** the slurm suite (`uv run pytest tests/... -m slurm`, timeout 600000) cancels a real job on the throwaway
  cluster; `make check` and `make check-clients` pass.
- **Phase 1, live end to end** (the real proof; not mocked):
  1. In a viva-pde-particle checkout, run `uv run vivarium-workbench serve --backend-base-url https://compose.cam.uchc.edu/`.
  2. Startup prints `backend dispatch: compose-api`.
  3. Run a study baseline. It is accepted, polls to completed, and lands rows in the study's `runs.db`.
  4. Its trace opens in Perfetto, and cancel works on a second run.
  5. The run is visible in compose-api's `/ui` with tags `workbench` and the study name.
  6. Capture screenshots with the browser tools.
- **Negative live probe:** a workspace with no registered environment gets the 409, and an unlisted class is caught
  by preflight before any POST.
- **Each PR:** run `/adversarial` before marking it done. Each fix ships with its tests and version bump in one PR,
  followed by tag → release → deploy.
