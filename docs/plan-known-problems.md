# Known problems: each solver's expected failures in a suite, curated by an admin, cleared when fixed

**Status (2026-10-26): steps 1, 2a and 3 done (0.7.47–0.7.49); step 2b (curating in the webapp) waits for the CSP.** It follows run 4 of biomodels-curated-300 on `registry_env@4`
([plan-environment-composition](plan-environment-composition.md), step 6) and borrows the known-faults pattern of
VCell's regression tests. One PR per step, each merged with a merge commit.

## Findings (2026-10-26)

1. **A suite's `expected:` list excuses a whole row, whatever solver it names.**
   - `Suite.expected_for(source)` (`sedml/suites.py`) ignores the entry's `solver` when the suite view
     (`sedml/suite_runs.py`, `view`) asks for a row.
   - The 9 Tellurium delay entries in biomodels-curated-300 therefore also excuse VCell's failures on those models. On
     24, 25, 34, 154, 155 and 196 only COPASI ran in run 4, so nothing was compared at all.
2. **A row whose one solver failed reads as "differ".**
   - Of the 26 models whose VCell import fails in run 4, COPASI and Tellurium agree on 24. Those rows show `close:
     false` only because the comparison is incomplete.
   - BIOMD 206 and 248 also have COPASI–Tellurium disagreements (5 and 2 labels). Excusing VCell must not hide them.
3. **VCell already keeps this list.** `BMDB_SBMLImportTest.knownFaults()` in vcell-core maps each BioModels number to
   a `FAULT` category, with the observed cause. A listed model's failure is excused, and an unlisted one fails the
   build. 20 of run 4's 26 VCell import failures are on it, so they are known VCell limits, not new findings.
4. **Nothing notices when a problem goes away.** libvcell 0.0.24 fixed six models, and the list would have had to be
   edited by hand to say so.
5. **Changing the list is a PR to `suite.yaml`.** That is slow for curation, and it is not a record of when each
   problem was seen or fixed.

## Decisions (proposed)

- **K1. A known problem is a database record, kept when cleared.**
  - It has the suite, source, solver (none for a problem before any solver runs, such as a translation failure), a
    `category`, a `reason`, the suite run it was first seen in, and who marked it and when.
  - Clearing sets `cleared_run` (the run that shows it fixed), who cleared it, and when. The record stays.
  - `category` is free text. VCell's problems use its `FAULT` names (`NONINTEGER_STOICH`, `DELAY`,
    `EXPRESSION_BINDING_EXCEPTION`, ...), so the two lists can be compared.
- **K2. A problem applies to the runs before the one that cleared it.**
  - A run numbered `n` is judged against every problem of its suite with no `cleared_run`, or with `cleared_run > n`.
  - Marking a problem therefore also excuses it in earlier runs; known problems are usually older than the run that
    first shows them. Clearing one does not change how earlier runs read.
  - Suite run numbers are monotonic per suite, so this needs no ordering across environments or versions.
- **K3. A problem excuses only its solver.**
  - The row's verdict comes from the pairs that do not involve an excused solver.
  - If those agree, the row is `excused` with the reasons. If they disagree, it is `differ`. If none are left (only
    one solver ran), it is `excused`.
  - A problem with no solver excuses the whole row, as `expected:` does today.
- **K4. A known problem that no longer occurs is flagged, not cleared.**
  - A solver is `resolved` in a row when it has an open problem there, its run completed, and it agrees with every
    solver it was compared with.
  - The row shows it, and the summary counts it. An admin clears the problem, which records the run that fixed it.
  - This is VCell's "the test passes, update the list". A pass after a timeout should not silently drop the entry.
- **K5. Each row gets one outcome**, and the summary counts each:

  | The solver | Known problem? | Outcome |
  |---|---|---|
  | fails or differs | yes | excused |
  | fails or differs | no | a new failure or disagreement |
  | completes and agrees | yes | resolved, to be cleared |
  | completes and agrees | no | agree |

- **K6. Curating needs a capability, `suites:curate`.**
  - A setting `suite_curator_role`, refused when it is `DEFAULT_ROLE` (as `admin_role` is), set to `admin` in
    `api.env`.
  - `/auth/me` lists the capability (plan-webapp-admin A1), and the webapp shows the controls only with it.
  - Reading problems is open, like the suite view.
- **K7. The CLI does one problem per command.**
  - There are few curation actions. Claude Code curates by reading `suites show --json` and the runs' logs, then
    running the commands in a loop or from a throwaway script. No bulk endpoint or file format is needed.
- **K8. `suite.yaml`'s `expected:` goes away.**
  - Its 11 entries (10 in biomodels-curated-300, 1 in biomodels-ode-sample) become records, made with the CLI.
  - Until the field is removed, the view treats each entry as an open problem with no `seen_run`.
  - Accepting a baseline stays a PR to `suite.yaml` (plan-webapp-admin A4).

## Steps

1. **API and CLI.**
   - Table `suite_known_problem` (id, collection, source, solver, category, reason, seen_run, marked_by, marked_at,
     cleared_run, cleared_by, cleared_at). It is a new table, so `create_all` makes it and no alembic revision is
     needed.
   - Routes:
     - `GET /suites/{name}/problems?cleared=` (`list-suite-problems`), open to everyone;
     - `POST /suites/{name}/problems` (`mark-suite-problem`): 400 for a source or solver the suite does not have, 409
       when a problem is already open for the source and solver;
     - `PATCH /suites/{name}/problems/{id}` (`edit-suite-problem`), for the category and reason;
     - `POST /suites/{name}/problems/{id}/clear` (`clear-suite-problem`), with the run that shows it fixed; 409 when
       already cleared, so a retry is safe.
   - The three writes need the `suite_curator_role` setting (K6; `SUITE_CURATOR_ROLE=admin` in `api.env`). The
     `suites:curate` capability on `/auth/me` comes with plan-webapp-admin step 3, which adds capabilities.
   - The suite view per K2–K5. `SuiteRunRow` gains `known_problems` (solver → reason), `excused` (the row fails or
     differs only through them) and `resolved` (solvers whose problem no longer occurs); its `close` is unchanged.
     The summary gains `excused` and `resolved`, and `differ` leaves out excused rows. `expected` stays, counting
     rows excused whole (a problem with no solver).
   - CLI, one level like every other group: `suites problems`, `suites mark-problem`, `suites edit-problem`,
     `suites clear-problem`. `suites show` prints the known, excused and resolved columns.
   - Tests: each outcome in K5, a cleared problem in an earlier and a later run, 401/403 without the role, the
     CLI commands.
   - Regenerate the spec, the client and `schema.d.ts`. Needs a release.
2. **Webapp**, in two parts.
   - **2a, read-only (no CSP dependency):**
     - a row's verdict reads `excused` when only solvers with a known problem fail or differ;
     - each solver's problem on the row: the solver (marked `resolved` when it now completes and agrees), its
       category and its reason;
     - `excused` and `resolved` summary badges, and a switch hiding excused rows;
     - a "Known problems" tab (`?tab=problems`), open and cleared, with when each was seen, marked and cleared;
     - Vitest tests for the row logic (`app/utils/suites.ts`).
   - **2b, curating:** with `suites:curate`, "Mark known problem" (solver, category, reason) on a solver that failed
     or differs, and "Clear" on a resolved one. Each opens a confirmation dialog, after the CSP is enforced
     (plan-webapp-admin A3). Vitest tests for the gating and the dialogs.
3. **Seed and remove `expected:`.** Done 2026-10-26.
   - Run 4's VCell import failures: 24 problems (ids 1–24), seen in run 4, each with VCell's own message as its
     reason and the category VCell's `knownFaults()` would give it: non-integer stoichiometry 9, delay 6, lumped
     kinetics units (`INCONSISTENT_UNIT_SYSTEM`) 5, expression binding 3, non-numeric stoichiometry
     (`NONCONSTANT_STOICH`) 1.
   - The 11 `expected:` entries became problems 25–35 (seen in run 1). Tellurium's on BIOMD 123 (CVODE convergence)
     and 152 (CVODE error test) were cleared at run 2, the first run in which Tellurium completes and agrees there.
   - Left as new failures: BIOMD 112 (`null` cause) and 175 (unknown identifier) until they are reported to VCell; 56
     and 168 (VCell disagrees), 137 (VCell's solve error), 235 (out of memory) and 255 (timeout).
   - `expected:` and `ExpectedFailure` are gone from `suites.py`, the suite files and `scripts/biomodels_suite.py`.
   - Seeding found one rule to fix (#404): a label neither solver of a pair reports (mostly reaction rates the SED-ML
     asks for) is not a disagreement between them. With it, run 4 reads 15 rows excused instead of 6.

## Verification

- **Unit tests:** the outcomes, `cleared_run` against run numbers, a solver-less problem, the capability check, and
  the CLI commands (`tests/client/test_cli.py` claims each operation).
- **Live:** after the seed, run 4's view shows 16 more rows excused, the 18 models whose only problem is VCell's import
  less 206 and 248, which still differ. 112 and 175 are new failures. Marking a problem against run 4 also excuses
  it in run 3; clearing one at a later run leaves run 4 unchanged.

## Later (not in this plan)

- **A suggested category for each new failure,** from the run log, using VCell's cause patterns (the step 3 seeding
  does this by hand).
- **Known problems outside suites,** such as one solver on a model across every comparison.
