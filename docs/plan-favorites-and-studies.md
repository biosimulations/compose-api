# Favorites and studies: a signed-in user's own runs, the runs they mark, and groups of runs they share

**Status (2026-10-28): in progress** (1a and 1c live in 0.7.70; 2 merged (#474); 1b in review). Asked for by Jim on 2026-10-28: a per-user favorites filter on the simulations
list, and then projects, studies or investigations. One PR per step, each merged with a merge commit; deploying is a
release, as usual.

| Step | What | State |
|---|---|---|
| 0 | This document | merged (#469) |
| 1a | Owners stamped at submit; a "Mine" filter (API, CLI, web); cancelling an owned run is its owner's | merged (#470) |
| 1b | Visibility chosen at submit and changed later (`PATCH`); private by default for a signed-in submitter (F3) | in review |
| 1c | No `Any` in the API's types: every error body declared, the client typed end to end (inserted 2026-10-28, before step 2's new routes) | merged (#471); 0.7.70 |
| 2 | Favorites: a private star on a simulation, a comparison or a suite run; a "Favorites" filter (API, CLI) | merged (#474) |
| 2b | The web pages: a star on each row and in each page's header; the Mine and Favorites filters | — |
| 3 | Studies: their own plan, settling S1–S4 below | — |

## Context

- **Ownership exists but is never set.** `simulation.owner_sub` and `visibility` were added in observability step 1
  (O7), and `can_read` already allows an owner, a public simulation, or a configured admin (`authorization.py`).
  Nothing stamps `owner_sub` at submit, so every simulation is anonymous and public. That is observability step 5,
  open since #192 (Auth0 sign-in) merged on 2026-10-08. This plan takes it over.
- **How a run's people are recorded today** (all in Postgres, written by the API; the SLURM job and the container
  never see any of it):
  - `simulation.owner_sub` and `visibility`: **ownership**, the only record of it (O7). Nothing sets `owner_sub`.
  - `submission.requested_by`: who asked for the run, "for fairness; not ownership" (durable submission, Q3). Nothing
    sets it either, and the submission worker never reads it: fair scheduling between users was not built.
  - `hpcrun`, events and datasets carry no owner; they reach the simulation by foreign key.
  - A suite run does not record who started it; `/suites/{name}/run` only logs it.
  - `/simulation/run`, `/sedml/run` and the curated routes log `describe_caller(principal)` and pass nothing on.
- **What groups runs today:**
  - a **comparison**: one SED-ML task run on several solvers (`docs/plan-sedml.md`);
  - a **suite** and its **suite runs**: a curated list of sources in the repository (`examples/<name>/suite.yaml`),
    run on demand and monthly;
  - **labels** the service writes (`source`, `model`, `project` for a biosimulations.org project, `collection` for a
    suite, ...) and **tags** the submitter gives. Both are fixed at submission, and both are public.

  None of these is a group a user makes after the fact, describes, and shares.
- **Vocabulary.** The life-science metadata standard is ISA (Investigation > Study > Assay), and FAIRDOM-SEEK adds
  Programme and Project above it. Here "project" already means a biosimulations.org project (the `project` label, and
  `biosimulations:` sources).

## Decisions (proposed)

- **F1. A run is owned by the signed-in caller who submitted it.**
  - `/simulation/run`, `/sedml/run` (each of its runs), the BioModels and biosimulations.org source shortcuts, and
    the curated routes stamp `owner_sub` from the principal, on the simulation, in the transaction that records it.
    Ownership is recorded there and nowhere else.
  - An anonymous submission has no owner, as now.
  - **Runs the service starts on its own have no owner:** a suite's runs (the monthly workflow, or a person pressing
    Run) and compliance runs. They belong to the suite or the environment, not
    to a person. *(Alternative: the person who pressed Run owns the suite's runs. Then "Mine" fills with 300 runs per
    press.)*
- **F2. An owner's identity is not shown to others.** A subject is an Auth0 id (`google-oauth2|1075…`), which says
  who someone is. Listings and pages say `mine: true/false` to the caller instead of naming the owner. Admins see the
  same.
- **F3. Visibility (step 1b): private by default, reconfirmed by Jim on 2026-10-28.** Observability's open
  question 1 was decided on 2026-10-07:
  *private by default for a signed-in submitter, with a flag to make a simulation public; anonymous submissions stay
  public.* Private by default has consequences that were not in view then:
  - a comparison is readable only when every member is (`/comparisons`), so a signed-in user's SED-ML comparisons
    disappear for everyone else, as do the suite pages' links to them if a suite's runs were ever owned (F1 says
    they are not);
  - a link to a run, sent to a colleague, stops working until it is made public.

  Step 1a changes no visibility. Step 1b makes a signed-in submitter's runs private unless they ask for public, and
  lets the owner change it later, which answers the colleague's link.
- **F4. Cancelling.** An owned run can be cancelled by its owner or an admin. An unowned one, by any signed-in caller
  who can read it, as now (the route's own comment anticipates this).
- **F5. A favorite is private to the user, and is not a tag.**
  - Table `favorite(user_sub, kind, ref, created_at)`, keyed on `(user_sub, kind, ref)`, with `kind` one of
    `simulation`, `comparison`, `suite_run`. Comparisons and suite runs are where triage happens, so they get stars
    from the start, in the same table.
  - Starring needs read access to the thing starred. A star on something that later becomes unreadable is kept, but
    is not listed.
  - Tags are given at submission, cannot change and are public, so they cannot serve as a personal mark.
- **F6. Studies come after, in their own plan.** Its decisions:
  - **S1. The name and the levels.** Proposed: one level, a *study*, rather than ISA's three or a "project" (taken).
    An investigation (a group of studies) can be added when someone needs it.
  - **S2. What a study holds.** Runs and comparisons for certain; probably the documents and composites they ran, so
    a study reads "inputs, runs, results". Suite runs?
  - **S3. Who may read and change it.** An owner, members with roles, and visibility. Members who can read a private
    study's runs is access through a relationship, not ownership. That is the case the Oso direction (declarative
    rules enforced in SQL) was kept for: the study plan adopts it, or says why not, rather than extending `can_read`
    by hand.
  - **S4. Publishing.** A study is the unit to export (RO-Crate, or a COMBINE archive) and to archive with a DOI
    (Zenodo), and the link back to biosimulations.org. The model leaves room for it; building it can wait.

## Work

### 1a. Owners stamped; "Mine"
- **Stamping.** `run_simulation` gains `owner_sub`, which it stores on the simulation; `/simulation/run`,
  `/sedml/run` (through `sedml.service.submit`), the source shortcuts and the curated routes pass the principal's
  subject. Suite and compliance runs pass none (F1). `submission.requested_by` is left as it is (open question 3).
- **The filter.** `GET /simulations?mine=true`: the caller's own runs; 401 when anonymous. A `mine` flag on each
  simulation in listings and on its page (F2). The CLI gains `simulations list --mine` (and its `@claims` stays with
  the existing command, since the operation is the same).
- **Cancelling** (F4) in `cancel_simulation`'s route.
- **The web page.** A "Mine" switch beside the simulations list's filters, shown when signed in.
- **Tests.** A signed-in submission is owned and an anonymous one is not; a SED-ML run's members are owned; a suite's
  and a compliance run's are not; `mine=true` lists only the caller's, and is a 401 anonymous; another user cannot
  cancel an owned run; the owner can.
- **No migration:** the column and its index exist.

### 1c. No `Any` in the API's types (asked 2026-10-28)
#470's new 401 widened `list-simulations`' generated return type to `Any`. 52 of 69 operations already returned an
`Any` union: an error response declared with a description and no body is typed `Any` by openapi-python-client.
- **Bodies** (`compose_api/api/errors.py`): `ErrorDetail` (`{detail: str}`) for every error, through `error(...)`;
  `SubmissionError`, `SedmlRunError` and `UnprocessableError` where `detail` is also structured (refused addresses,
  a translation's findings, request validation). Refusals are raised from those models.
- **Files** declare `type: string, format: binary` (a zip through a content-type override), so the client returns
  `File`; the Chrome trace declares its `TraceDocument`.
- **The client layer**: `_parsed(response, Model)` and `_parsed_list` check the body's type; 88 `type: ignore`s gone;
  JSON is `JsonValue`, not `Any`.
- **Server code**: upstream answers (BioModels, biosimulations.org, biosim's /verify) validated into models; no
  function parameter or return is `Any` (ruff `ANN401`, `*args`/`**kwargs` excepted; tests exempt).
- **Guards**: `tests/api/test_error_bodies.py` fails on a response with no body schema, or a generated operation
  returning `Any`.
- **A client behaviour change**: a declared error status now parses its JSON body (an `ErrorDetail`) instead of
  `None`; a non-JSON body for a declared status (an ingress's HTML 502) raises in the generated functions. The CLI
  and `ext` layer already read such an answer as unreadable and classify it by status; pbest checks the status first.

### 1b. Visibility (F3: private by default)
- `visibility` on every route that stamps an owner: `/simulation/run`, `/sedml/run`, the source shortcuts and the
  curated routes. Signed in, it defaults to private; anonymous, the run is public and asking for private is a 400
  (a run with no owner that nobody may read helps nobody). `authorization.ownership_at_submit` decides, and the
  owner and visibility travel together as `Ownership` to the simulation row.
- `PATCH /simulations/{id}` with `{visibility}`, by the owner or an admin (403 otherwise, and for a run with no
  owner, which stays public). The other runs of every comparison it is in change with it; if any of them is not the
  caller's to change, nothing changes (409).
- CLI: `--visibility` on `run`, `curated`, `sedml run`, `biomodels run`, `biosimulations run`;
  `simulations visibility <id> public|private`.
- The web pages: the choice on the new-simulation, composite and SED-ML pages (signed in only); on a run's page its
  visibility, and "Make public/private" for its owner; a lock beside private runs in the simulations list, which
  also drops its Simulator, Experiment and SLURM job columns and its view and download buttons: a row opens its
  run, whose page has the rest (Jim, 2026-10-28).

### 2. Favorites
- The `favorite` table (F5), created by `create_all` (a new table needs no revision).
- `PUT` and `DELETE /favorites/{kind}/{ref}`, `GET /favorites[?kind=]`, signed in only; `favorite=true` on
  `GET /simulations` and `GET /comparisons`; a `favorite` flag on each simulation and comparison.
  - `ref` is a simulation's or a comparison's id, or a suite run as `<suite>@<number>`, stored normalized.
  - `PUT` is idempotent and needs read access (404 otherwise); `DELETE` answers whether there was a star, not a 204,
    because a response without a body is typed `Any` by the generated client (step 1c).
  - Suite runs carry no flag: the web page asks `GET /favorites?kind=suite_run`.
- CLI: `compose-api favorites add|remove|list`, and `--favorite` on the list commands.

### 2b. The web pages
- A star on each row of the simulations and comparisons lists and in each page's header, and on a suite run's page.
- "Mine" and "Favorites" filters, shown when signed in.

### 3. Studies
A plan of its own, `docs/plan-studies.md`, settling S1–S4, written once favorites are live and the shape of what
people group is visible.

## Verification
- Unit and API tests per step, as above.
- **Live after 1a:** a run submitted signed in from the web UI shows under "Mine"; one submitted with the CLI
  anonymously does not; `compose-api simulations list --mine` agrees.
- **Live after 2b:** a star on a simulation, a comparison and a suite run shows under Favorites, and not for another
  account.

## Open questions
1. ~~F3: private or public by default for a signed-in submitter.~~ Private (Jim, 2026-10-28).
2. F1's alternative: should the person who presses a suite's Run own its runs?
3. `submission.requested_by` is never set and never read. Drop it (a migration), or keep it for fair scheduling when
   that is built? Separately, should a suite run record who started it (`suite_run.started_by`, a migration)?
