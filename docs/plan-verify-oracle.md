# The BioSimulators verify oracle: checking our SED-ML comparisons against biosim's `/verify` API

**Status (2026-10-28): V0–V4 merged; V5 in review.** Linking out to biosim.biosimulations.org pages is deferred: the platform's UI does
not use verification yet. Its `/utilities/verify-model` card is a dead link (`frontend/app/pages/utilities/index.vue`
at `62bc540`), and project and run pages have no verification view to link to. This plan uses the API directly. One
PR per step, each merged with a merge commit; deploying is a release, as usual.

| Step | What | State |
|---|---|---|
| V0 | This document | merged (#341) |
| V1 | Legacy runs as references: a `biomodels:` source's original biosimulations.org run (no new simulation) | merged (#342), released 0.7.33 |
| V2 | A client for the verify API, and a durable `verification` record per comparison | merged (#344) |
| V3 | The verification worker: submit within the rate limit, poll, store, fold into the comparison | merged (#344) |
| V4 | Triggers: one comparison on demand (API + CLI), and a suite option (`verify:`) | merged (#348, #351) |
| V5 | Surface: the comparison page and the suite summary show each verification's verdict | in review |

## Context

A comparison (`docs/plan-sedml.md`) runs one SED-ML task on our solvers (COPASI and Tellurium, through the
biosim-toolkit steps) and scores them against each other with `compose_api/sedml/compare.py`. When the solvers agree,
that is evidence. When they differ, or one fails, we cannot tell from our own two runs which is right, or whether our
adapters are at fault rather than the solvers.

The first run of `biomodels-curated-300` (2026-10-22, suite run 1) shows the scale of that gap:
- 294 comparisons;
- 198 where both solvers ran and agree;
- about 27 where both ran and differ, 20 of them by more than 1000 times the tolerance;
- 69 where at least one solver failed (73 failed runs: 32 COPASI, 41 Tellurium).

biosim's API (`https://api.biosim.biosimulations.org`, biosim-server 0.10.1, platform `main` at `62bc540`) offers an
independent oracle.

- **`POST /verify/omex`** takes a COMBINE archive (multipart, up to 20 MB through the public ingress). It runs the
  archive on BioSimulators' own simulator images: AMICI, COPASI, PySCES, Tellurium and VCell by default, `name` or
  `name:version`, at most 10. The runs happen on the legacy runBioSimulations service (`api.biosimulations.org`), one
  per simulator. It then compares every pair.
  - **Asynchronous:** it returns a `workflow_id` straight away (`PENDING`), to poll with
    `GET /verify/{workflow_id}`. A run takes minutes, bounded by a 10-minute timeout per simulator.
  - **A simulator whose run fails is dropped** from the comparison; it does not fail the verification.
- **`POST /verify/runs`** compares runs that already exist, by biosimulations.org run id (at most 10). It runs nothing.
- **The comparison is the same as ours.** Per SED-ML report and label, `score = max |a−b| / (atol + rel_tol·|b|)`, with
  `atol = max(abs_tol_min, max|a|·abs_tol_scale, max|b|·abs_tol_scale)`. It takes the same knobs and defaults: `rel_tol`
  1e-4, `abs_tol_min` 1e-3, `abs_tol_scale` 1e-5. `include_outputs=true` returns each simulator's series as well.
- **The result** (`VerifyWorkflowOutput`):
  - `workflow_status`: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED` or `RUN_ID_NOT_FOUND`;
  - `workflow_results.sims_run_info`: each simulator's biosimulations.org run;
  - `workflow_results.comparison_statistics`: per dataset, an N×N matrix of `{simulator_version_i, simulator_version_j,
    var_names, score, is_close, error_message}`;
  - optionally `sim_run_data`, the series themselves.
- **Auth and limits:**
  - Anonymous calls are allowed, and a verification created anonymously is readable by anyone.
  - A token records `owner_sub` and restricts reads to the owner.
  - `/verify/*` and `/simulations/run` share a budget, counted per API pod: 5 per minute per IP when anonymous, 30 per
    minute when authenticated (429 with `Retry-After`).
  - Temporal does not keep results forever: an old `GET` answers 404, so we store what we read.
- **The legacy projects cover our suite.** 275 of the first 300 BioModels entries already have a biosimulations.org
  project, named `BIOMD<id>_<simulator>_<title>`, each with a run of AMICI, COPASI, PySCES or Tellurium. 26 entries have
  two such projects.

## Decisions (proposed)

- **D1. The oracle is a reference, not an arbiter** (as `docs/plan-sedml.md` D7 says for references). A comparison's
  `close` stays our solvers' agreement. The oracle adds:
  - each BioSimulators simulator's result as a **reference series** (`origin = biosimulators:<name>:<version>`), scored
    against each of our solvers by our own `compare.py`, so `close_to_references` covers them;
  - **the oracle's own verdict:** whether the BioSimulators simulators agree with each other (`verify_close`), as
    `/verify` reports it.

  Together these say which side is wrong:
  - our solvers differ, and BioSimulators agrees with COPASI: Tellurium, or our Tellurium adapter, is wrong;
  - BioSimulators disagrees with itself: the model is hard, and no one solver is at fault.
- **D2. The cheapest oracle comes first (V1).** For a `biomodels:` source, the legacy project's existing run is already
  a BioSimulators result. Its `outputs/reports.h5` is attached as a reference, as `biosimulations:` sources already do
  (`sources.project_reference`). The project is found by its `BIOMD<id>_` prefix in the list
  `sources._projects()` already caches. It costs no simulation and no rate budget.
- **D3. `/verify/omex` runs only where V1 cannot settle the question.** By default:
  - comparisons that differ or are incomplete;
  - sources with no legacy project;
  - on demand.

  It does not run on every source of every suite run: a monthly 300-model run with 5 simulators would be 1,500 runs
  on the shared legacy service. The suite option chooses (V4).
- **D4. We submit what we ran.** The archive sent to `/verify/omex` is the one the comparison translated: the
  `sedml-omex` dataset, `source.omex`. Its SED-ML and models then match ours, and the dataset names (`<sedml>/<report>`)
  line up with our reports. `include_outputs=true` brings back the series for D1. The tolerances are the comparison's
  own.

  **Amended (2026-10-22): minus manifest entries for files it lacks.** BioModels archives often list files they do not
  ship (13 in BIOMD0000000012's), and BioSimulators refuses such an archive: its runs fail, and before platform#154 the
  verification even came back `COMPLETED` with no runs. `verify.sanitize_archive` drops those entries and nothing
  else; the dropped locations are kept on the verification (`settings.dropped_manifest_entries`). BIOMD0000000012
  cleaned this way ran on COPASI, Tellurium and AMICI, all three close to each other.
- **D5. Durable and rate-limited, like the submission queue** (`docs/plan-durable-submission.md`). A `verification` row
  per request, with state `requested → submitted → completed | failed`, the `workflow_id`, and the stored result. The
  submission worker gains a verification step:
  - it leases due rows;
  - it submits within a token bucket under the API's budget, by default 4 per minute anonymous or 25 authenticated;
  - it honours 429 `Retry-After`;
  - it polls submitted ones every 30 s.

  A restart resumes it. A result read once is kept, so Temporal's retention doesn't matter.
- **D6. Authenticate as a service, when a client exists.** An Auth0 client-credentials application for compose-api
  (in auth0-pulumi, alongside the CLI and SPA applications) raises the budget to 30 per minute and keeps our
  verifications from being publicly readable. Until it exists, calls are anonymous within 5 per minute. The client
  secret is a secret (`SECRET_ENV_FILE`), not `api.env`.

## Work

### V1. Legacy runs as references (no new simulation)
- **The lookup.** `sources.legacy_projects(biomodel_id) -> list[ProjectInfo]` returns the projects whose id starts with
  `f"{biomodel_id}_"`, from the cached `/projects` list.
- **Attaching them.** In `suite_runs._submit_source`, and in `/sedml/run` for a `biomodels:` source, each such project's
  `project_reference` is attached as a reference, `origin = f"biosimulations:{project.simulator or project.id}"`, which
  is the shape `biosimulations:` sources use.
- **Effect:** the next suite run reports `close_to_references` for about 275 of 300 sources.
- **Tests:** recorded fixtures (`tests/fixtures/resources/sources`, `recorded_sources`). A `biomodels:` source with a
  legacy project gets its reference; one without gets none.

### V2. The client and the record
- **The client.** `compose_api/sedml/verify.py`, an httpx client for `POST /verify/omex`, `POST /verify/runs` and
  `GET /verify/{workflow_id}`.
  - Its models mirror biosim's `VerifyWorkflowOutput`, `ComparisonStatistics` and `CompareSettings`, kept in step
    with biosim-server by a recorded response fixture.
  - Settings: `biosim_api_url` (default `https://api.biosim.biosimulations.org`), `verify_simulators` (the default
    five), and the token settings of D6.
- **The table.** `verification`, created by `create_all`:

  | Column | Meaning |
  |---|---|
  | `id` | key |
  | `comparison_id` | FK |
  | `kind` | `omex` or `runs` |
  | `simulators` | JSONB |
  | `settings` | JSONB: the tolerances sent |
  | `state` | `requested`, `submitted`, `completed`, `failed` |
  | `workflow_id`, `workflow_status` | as biosim reports them |
  | `result` | JSONB: the stored `VerifyWorkflowOutput` |
  | `attempts`, `next_attempt_at`, `last_error` | retry bookkeeping |
  | `lease_owner`, `lease_expires_at` | the worker holding it |
  | `created_at`, `updated_at` | |

  It is a new table, so `create_all` makes it with its index on `(state, next_attempt_at)`; no revision is needed.

### V3. The verification worker
- **Where it runs.** Inside `SubmissionWorker` (`compose_api/simulation/submission_worker.py`), alongside suite runs,
  with the same lease pattern.
- **`requested`:** fetch the comparison's `source.omex` (`sedml-omex` dataset), then `POST /verify/omex` with
  `include_outputs=true` and the tolerances, inside the token bucket. Record the `workflow_id` and move to `submitted`.
  - A 429 defers the row by `Retry-After`.
  - A 5xx or a network error is retried with the queue's backoff.
- **`submitted`:** `GET /verify/{workflow_id}` every 30 s, until `COMPLETED`, `FAILED` or `RUN_ID_NOT_FOUND`, or a
  deadline (default 60 min).
- **On `COMPLETED`:**
  - store the output;
  - turn `sim_run_data` into references, one per BioSimulators simulator (D1), mapped to our report ids by
    `<sedml>/<report>`;
  - recompute the comparison (`service.comparison_view`), so `close_to_references` includes them;
  - record `verify_close` from `comparison_statistics`.
- **A simulator whose run failed at biosimulations.org** is recorded as absent, with its run id, not as a failure of
  the verification.

### V4. Triggers

**As built.**
- `POST /comparisons/{id}/verify` takes an optional body, `{"simulators": [...]}`; without one it uses
  `verify_simulators`. It answers 201 with the new verification, or 200 with the one already queued or running for the
  same simulators, so asking twice costs biosim nothing.
- `POST /suites/{name}/runs/{number}/verify?which=failing|all` replaces the planned
  `comparisons verify --suite … --run … --failing`. The CLI commands are `comparisons verify`,
  `comparisons verifications` and `suites verify NAME NUMBER [--all]`.
- **"failing" means** a finished comparison whose solvers differ, that is incomplete, or that no agreeing reference
  settles: none (no legacy project), or one that disagrees.
- **`verify:` applies when a comparison is scored.** That happens when the comparison or its suite run is read, as
  the monthly suites workflow does; nothing scores comparisons in the background.
- **Resuming (2026-10-22, after the first triage).** `verify_deadline_seconds` is 6 hours, not 1: 34 of 96
  workflows were still `IN_PROGRESS` at biosim after an hour. Asking to verify again resumes a verification that
  failed while its workflow was unfinished (past the deadline, or out of attempts reading it), polling the same
  `workflow_id` with a fresh deadline. One biosim itself failed is submitted afresh.
- **The suite run's view** (`GET /suites/{name}/runs/{number}`, not yet the web page) gives each row's newest
  verification and its `verify_close`, and the summary counts `verifying`, `verified` and `oracle_agrees`. *(Corrected
  2026-10-28: the web pages showed none of it until V5.)*
- **One comparison, on demand.**
  - `POST /comparisons/{id}/verify` queues one (`kind=omex`). `GET /comparisons/{id}/verifications` lists them.
  - Their `operation_id`s get CLI commands (`compose-api comparisons verify`, `… verifications`), since the `@claims`
    rule needs them.
  - `make clients` regenerates the client.
- **A suite option.** `suite.yaml` gains `verify: none | failing | all`, default `none`.
  - `failing` queues a verification for each comparison that differs or is incomplete, and for sources with no legacy
    project, once the suite run's comparisons are complete.
  - The suite page counts them.
- **A batch run without a suite.** `compose-api comparisons verify --suite biomodels-curated-300 --run 1 --failing`
  covers suite run 1 after the fact.

### V5. Surface
- **The comparison page** (`webapp/app/pages/comparisons/[id].vue`) shows each verification: its state, the simulators
  that ran, `verify_close`, and the oracle's series in the overlay. The "Original results" column covers the new
  references.
- **The suite page and `SuiteRunView.summary`** gain `verified` and `oracle_agrees_with: {copasi, tellurium}` counts.
  These are what the 300-model triage needs.
- *As built (2026-10-28):*
  - **Which solvers the oracle sides with** (`verify.agrees_with`): a solver of ours whose every data set scored
    against a completed verification's references (`solver|biosimulators:<name>:<version>` pairs) is close. A pair
    missing on one side is no evidence either way, and a solver with nothing scored against them is not counted. It
    does not also require `verify_close`: a solver close to every one of the simulators is so whether or not they are
    close to each other.
  - **The API:** a `Verification` gains `agrees_with` (`GET /comparisons/{id}/verifications` scores it against the
    comparison); a suite run's row gains `oracle_agrees_with`, from its newest verification; the summary gains
    `oracle_agrees_with_<solver>` for each solver the run's comparisons use, flat because the summary is
    `{name: count}`.
  - **The comparison page** has a "Checked against BioSimulators" card: each verification's verdict (agrees, with
    which of our solvers; disagrees, so the model is hard; verifying; not verified), its simulators by version, those
    that produced no results and why, and a Verify button for a signed-in caller once the comparison has finished and
    none is going. The page polls while one is. The overlay draws each BioSimulators simulator in a colour of its own,
    legacy runs still grey.
  - **The suite page** has a BioSimulators column and, once anything is verified, a line of counts: verifying,
    verified, its simulators agree, and "sides with <solver>" per solver. Verifying a whole run stays in the CLI
    (`suites verify`), because of open question 2.
  - The verdicts are pure functions (`webapp/app/utils/verify.ts`) with their tests.
- **Not in this plan: links to biosim pages.** The legacy run ids are stored (`sims_run_info`), so they can be added
  when the platform's UI shows verifications or runs we can link to.

## Verification

- **Unit tests** (recorded responses, httpx `MockTransport`):
  - the client's models against one real `VerifyWorkflowOutput`, captured once from the live API for BIOMD0000000012;
  - the mapping from `comparison_statistics` and `sim_run_data` to references, and `verify_close`;
  - the worker's states: submit, 429 with `Retry-After`, polling to `COMPLETED`, `FAILED`, the deadline, and a restart
    mid-poll resuming with the same `workflow_id`;
  - the token bucket staying under its budget.
- **A live check, by hand.** Verify one agreeing comparison (BIOMD0000000012) and one disagreeing one from suite run 1.
  The agreeing one shows BioSimulators close to both our solvers. The disagreeing one says which side BioSimulators
  takes.
- **The triage run.** `--failing` on `biomodels-curated-300` run 1, about 100 comparisons at 4 per minute, roughly 25
  minutes of submission and then polling. The result sorts the 96 differing or incomplete comparisons into: our
  adapter is wrong, the other solver is wrong, or the model is hard.

## Open questions

1. **A service account in Auth0** (D6): who creates it, and does biosim want compose-api's verifications visible to its
   admins? (Novrus owns auth0-pulumi; the platform's owner decides the second.)
2. **The volume biosim is happy with.** A one-off triage of about 100 archives is about 500 runs on the legacy service.
   A monthly `failing` run would be similar. Check with the platform's owner before turning `verify: failing` on for a
   scheduled suite.
3. **VCell's dataset names.** VCell's BioSimulators image names reports as the SED-ML does, but its labels can differ in
   case. Check on the first live verification, before mapping its series to our labels.
