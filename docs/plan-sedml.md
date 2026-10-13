# SED-ML models as process-bigraph runs across solvers, compared

**Status (2026-10-13): every phase merged; phases 0 to 5 released in 0.7.18, phase 6 in 0.7.19; verified on the cluster with 0.7.21 (see "Verification"), the suites' baselines set to their first runs.** One PR per phase and repository, merged with a merge commit on
the maintainer's word; each PR updates the table below. A merge deploys nothing by itself: the next release's image
ships it (CLAUDE.md, "Deploys are GitOps"). The language side is planned in process-bigraph-lang's
[`docs/v2/sedml-plan.md`](https://github.com/biosimulations/process-bigraph-lang/blob/main/docs/v2/sedml-plan.md).

| Phase | What | Repo | State |
|---|---|---|---|
| 0 | Labels, tags and a description on simulations, and filters on them; the concepts below documented; `GET /registry/entries` and `/ui/catalog` rebuilt on it | compose-api | merged (#283) |
| 1 | SED-ML read into a `.pblang` template per task with the solver as an open site, one checked instance per solver; plots built at run time; release 0.3.0 | process-bigraph-lang | merged (#58, #59, #60); released 0.3.0, 0.3.1 |
| 2 | SED-ML adapter steps around generic COPASI and Tellurium steps; `solvers.yaml` and `GET /registry/solvers` | biosim-toolkit 0.1.0 (released), compose-api | merged (#284) |
| 3 | `POST /sedml/run` and `/sedml/preview`; the `sedml-omex` and `input` datasets; comparisons computed on the server | compose-api | merged (#285) |
| 4 | BioModels and biosimulations.org source routes, cached; run shortcuts; references (original results); the curated routes on the same path | compose-api | merged (#286; the curated routes and interpolation deferred) |
| 5 | Web app: ad-hoc SED-ML page, sources, a Plotly viewer, the comparison page | compose-api `webapp/` | merged (#287) |
| 6 | Regression and reproducibility suites, rerun on a schedule, with their pages | compose-api | merged (#289); the `smoke` suite added |

Phases 0, 1 and the inventory that opens phase 2 do not depend on each other. Phase 3 needs 1 and 2.

## Why

The reproducibility goal (goals.md G4, G5) asks that a result not depend on which implementation produced it. The
most direct evidence is to run the same workflow on several implementations of the same role and compare, and to
keep doing it as images, solvers and translators change. Thousands of such workflows already exist, described in
SED-ML inside OMEX archives: every curated BioModels entry, and the projects on biosimulations.org, many of which
carry the results of their original run.

Today this service runs process-bigraph documents only. The curated COPASI and Tellurium routes render one fixed
Jinja document (whose defects the composite viewer's checker shows: an `interval` on a step, a config key the step
does not have), `btools/sedml_compiler` is not wired to any route, runs carry no labels to find them by, nothing groups
runs, and nothing compares results.

## Decisions (2026-10-12)

| | Decision | Considered | Why |
|---|---|---|---|
| D1 | **SED-ML is translated by process-bigraph-lang** into a `.pblang` template with the solver as an open address site, checked and filled once per solver | a Python generator here (revive `btools/sedml_compiler`); translating inside the job at run time | every document is checked against its environment's manifest before it runs; the translation is readable text (the viewer, "Edit a copy"); it exercises `.pblang` and its SBML model headers; it is usable outside this service. The job-side option leaves the input as SED-ML, so the run's input would not be the document that ran |
| D2 | **One simulation per solver**, grouped by a comparison | one document with every solver's step side by side | solvers in different images can be compared; one solver's failure does not taint the others; each result is attributable to exactly one implementation and environment. Proven at scale in the platform's verification workflows |
| D3 | **Labels and tags on simulations, plus comparison tables** | labels only (a comparison as a saved query); a project/study hierarchy | a comparison's result and its members are durable records; labels make everything else a query |
| D4 | **Comparisons are computed on the server, from CSV reports** | in the browser; inside a document; HDF5 reports | a stored result per comparison; CSV is what the web app already plots. The metric is the platform's: per variable, `max |a−b| / (atol + rtol·|b|)` with `atol = max(abs_tol_min, max|a|·s, max|b|·s)`, defaults `rtol 1e-4`, `abs_tol_min 1e-3`, `s 1e-5`, close when below 1 |
| D4b | **SED-ML plots become Plotly figures** | Vega-Lite specs (what biosimulations.org projects ship); static images | Plotly is already in the web app, and traces from several runs overlay on the comparison page |
| D5 | **Both regression suites in this repository and on-demand runs from a source or an upload** | collections as database rows edited in the UI | suites are reviewed and versioned like `manifest.yaml`; ad-hoc runs explore. A collection is only a label, so database collections can come later without a schema change |
| D6 | **Solvers are generic COPASI and Tellurium steps wrapped by SED-ML adapter steps** | SED-ML-specific solver steps per simulator | SED-ML semantics (model changes, output start time, data generators, reports, plots) are written once; solvers stay generic. COPASI and Tellurium first (both in `registry_env`) |
| D7 | **biosimulations.org's original results are a reference**, not a candidate | | a reference column in the comparison |
| D8 | **SED-ML scope, version 1**: uniform time course tasks, attribute model changes, simple data generators, reports, plots | steady state, repeated tasks, math in data generators | what most curated models use; anything else is reported, never dropped silently |
| D9 | **Runs stay anonymous**: tags and description are given at submission and not edited | owner edits | submissions carry no owner today |
| D10 | **SED-ML model changes are applied at translation** (2026-10-13): the instance's solver reads a changed copy of the SBML, and the `.pblang` text's `meta` lists each change | a changes step before the solver | changes are constants; the generic solvers read their model from config, which no step can change at run time |
| D11 | **The SED-ML adapters are a new package this project owns** (2026-10-13), `pbsim_sedml` until named; registered in `manifest.yaml` and installed in `registry_env` | adding them to pbsim-common; shipping them in process-bigraph-lang | our release cadence and tests; process-bigraph-lang keeps process code out of its package |

**How this feeds the curation ladder.** strategy.md decision 5 defines `validated` as "at least one study whose
findings confirm against a published reference or an independent simulator". A passing comparison (phase 3) is that
evidence for each solver's registry entry, and a suite (phase 6) keeps it current; recording it in `manifest.yaml`
stays a reviewed change.

## Concepts: catalog, registry, environment, solver

Three things are called a catalog today (viva-catalog upstream, `catalog.yaml`, and the web app's `/catalog` page,
which shows the stale Postgres `/core/*` tables). Each concept gets one job:

| Concept | The question it answers | Source of truth | Served at |
|---|---|---|---|
| **Catalog** | What exists in the ecosystem, and how far each thing is trusted (discovery and trust, not runnability) | `catalog.yaml` (generated from viva-catalog) merged under `manifest.yaml`: entries, level, pin, evidence | `GET /registry/entries`; `/ui/catalog`, each entry linked to the environments that provide it |
| **Registry of record** | What may run here (admission) | `manifest.yaml` levels: `tested` and above run on HPC | the submission checks |
| **Environment** | Where a document runs, and the exact classes, ports and config its image provides (execution, not trust) | `environments.yaml`, `manifests/<env>.json` | `/registry/environments`, `/ui/environments` |
| **Solver** | Which implementation of a role a comparison runs: an environment's class, the algorithms (KiSAO terms) it implements, how SED-ML maps onto its config | `solvers.yaml` | `GET /registry/solvers`; the "run on" picker |

The Postgres `/core/*` routes are kept and marked deprecated. Generating `simulation/simulator_registry.json` (what
goes into the shared image) and `manifest.yaml` (what is admitted) from one list is a follow-up.

## What a SED-ML run is

1. **The source.** An uploaded SED-ML OMEX, a BioModels entry (EBI's `GET /biomodels/model/download/{id}` is a
   COMBINE archive holding the SBML and a SED-ML), or a biosimulations.org project (`GET /runs/{run}/download`; its
   original results are `GET /results/{run}/download`, an `outputs/reports.h5`).
2. **The translation** (process-bigraph-lang, phase 1). Each SED-ML task becomes a composite: the SBML model header,
   a model-changes adapter, `simulate : TimeCourseSolver at ?` (the open site), a data-generators adapter, a report
   step writing one CSV per SED-ML report, and a plots step filling one Plotly template per SED-ML plot. The checker
   verifies each solver against the `TimeCourseSolver` role in that solver's environment; a solver that does not fit,
   or does not implement the requested algorithm, is refused with the findings.
3. **The runs** (phase 3). One simulation per accepted solver, labelled `source`, `model` or `project`,
   `sedml_task`, `solver`, `comparison` (and `collection`, `suite_run` for a suite). Each has two archives:
   - **`sedml-omex`**: the original archive, as received (`sims/<job>/source.omex`), with
     `{source, model|project, sedml[], upstream_version}` in its attributes;
   - **`input`**: the generated archive (model files, the `.pbg`, its `.pblang` text, the plot templates), as for any
     run, so the composite viewer and "Edit a copy" work unchanged.

   and outputs: report CSVs (kind `table`) and figures (kind `figure`, `application/vnd.plotly.v1+json`).
4. **The comparison** (phase 3). When the last member is terminal, a background task reads the members' report CSVs
   and any references (the original results, converted to CSV), scores each variable pairwise across solvers and
   against each reference (interpolating onto the reference's time grid when grids differ, and saying so), and
   stores the result. A failed member is shown failed, not dropped.

## Phase 0: what exists after it

- `simulation.labels` (JSONB), `simulation.tags` (text[]) and `simulation.description`, with GIN indexes (migration
  `3f9a6c1e7b24`). The reserved label keys and the rules for tags are `compose_api/simulation/labels.py`:
  `source`, `environment`, `solver`, `model`, `project`, `sedml_task`, `comparison`, `collection`, `suite_run`.
- `POST /simulation/run` takes `tags` (repeatable) and `description`, and labels the run `source=upload` and
  `environment=<simulator or registry_env>`. The curated routes label theirs `source=curated`, `solver=copasi|tellurium`,
  `environment=registry_env`. Runs submitted before this carry none.
- `GET /simulations` and `GET /simulations/{id}` return them; `GET /simulations?label=key:value&tag=name` (each
  repeatable, all must match) filters by containment. The CLI: `run --tag --description`, `simulations list --label
  --tag`, `catalog`.
- `GET /registry/entries`: every registry entry, most trusted first, with its pin, evidence and the environments whose
  manifest lists its classes. `/ui/catalog` shows it (levels as strategy.md defines them, links to each environment's
  page); the Postgres `/core/*` lists are marked deprecated in the API.
- The web app: label and tag chips on the simulations list and a run's page (a chip filters the list), label and tag
  filters in the list's query string, and tags and a description in the run form.

## Phase 2: what exists after it

- **biosim-toolkit** ([biosimulations/biosim-toolkit](https://github.com/biosimulations/biosim-toolkit), 0.1.0 on
  PyPI): a rollup of trusted utilities (D11; SED-ML, model and format adapters, reports, data, visualization).
  Its SED-ML steps are `local:biosim_toolkit.sedml.{DataGenerators, Report, Plots}`; its CI runs translated archives
  end to end on registry_env's versions with real COPASI and Tellurium. Installed in registry_env
  (`simulation/simulator_registry.json`), so the shared image's hash and its manifest change; registered at `tested`
  in `manifest.yaml`, gated by `tests/simulators/test_sedml.py` (cluster only: the Ciliberto project on both
  solvers inside the built image, which must agree).
- **`registry/solvers.yaml`**: `copasi` (`CopasiUTCStep`, LSODA/LSODAR and LSODA) and `tellurium`
  (`TelluriumUTCStep`, CVODE), both returning species. `tests/registry/test_solvers.py` checks each against its
  environment's committed manifest (the class exists, at `tested` or above, with the role's face).
  `GET /registry/solvers`; CLI `solvers`.
- What the generic solvers do, found while building (process-bigraph-lang `docs/v2/sedml-plan.md`): they share one
  face, start at time 0, take points not steps and return species only; process-bigraph 1.0.5 runs steps when the
  composite is built; bigraph-schema 1.0 drops new keys on a `map` update, so the data store overwrites.

## Phase 3: what exists after it

- **The translator runs in its own environment.** process-bigraph-lang needs bigraph-schema 1.6; this service's
  environment has pbest's 1.0. `compose_api/sedml/translator.py` runs its CLI (`sedml describe`, `sedml translate`)
  with `settings.pblang_python` (`.pblang/`, made by `make pblang` and by the API image from
  `compose_api/sedml/pblang-requirements.txt`) and reads what it writes: one archive per task and solver, the
  template text, `findings.json`.
- **`POST /sedml/preview`** (an archive, optional `solvers`): each task's template, the solvers that accept it and
  those refused, its reports, and every finding. Nothing runs.
- **`POST /sedml/run`** (an archive; `solvers`, `task`, `tags`, `description`, tolerances): per accepted task, a
  comparison and one run per accepting solver, through the same submission check and `run_simulation` as any
  upload. Each run is labelled `source`, `environment`, `solver`, `sedml_task`, `comparison`; its input is the
  translated archive and it carries the original (`SimulationRequest.source_file_path`), uploaded beside the input
  as `source.omex` and announced by the job script as a **`sedml-omex`** dataset. A task no solver accepts is a 400
  with the findings.
- **`GET /comparisons`, `GET /comparisons/{id}`**: a comparison's members and their states. When every member has
  finished, the comparison reads each member's report CSVs from its experiment directory, scores every data set
  label for every solver pair (`compose_api/sedml/compare.py`, the platform's score), stores the result and its
  status (`complete`, or `incomplete` when a member did not complete), and says whether every pair is `close`.
  Columns of different lengths are reported, not scored: interpolation onto a common grid comes with references in
  phase 4.
- Tables `comparison` and `comparison_member` (created at startup). CLI: `sedml preview|run`,
  `comparisons list|show`.

## Phase 4: what exists after it

- **`compose_api/sedml/sources.py`**: EBI BioModels (search, limited to manually curated models unless
  `curated=false`; metadata with the latest revision; the COMBINE archive) and biosimulations.org (project search by
  id, a project with the simulator that ran it, its archive, its original results). Archives are cached on disk by
  id and upstream revision (`settings.sources_cache_dir`); lists and metadata for an hour in memory.
- **Routes** (`routers/sources.py`): `GET /sources/biomodels/search?q=`, `/sources/biomodels/{id}`,
  `/sources/biomodels/{id}/omex`; `GET /sources/biosimulations/projects?q=`, `/sources/biosimulations/{project}`,
  `/{project}/omex`, `/{project}/reference`; and `POST /sources/biomodels/{id}/run`,
  `POST /sources/biosimulations/{project}/run`, which run the archive as `/sedml/run` does, labelled
  `source=biomodels, model=…` or `source=biosimulations, project=…`.
- **References** (D7): a `comparison_reference` per origin, matched to the comparison's SED-ML file and reports. A
  biosimulations.org project's original results (its run's `outputs/reports.h5`, origin
  `biosimulations:<simulator>`), and any `reports.h5` shipped in an uploaded archive (origin `archive`), are scored
  against each solver as `solver|origin`; `close` stays the solvers' agreement, `close_to_references` says whether
  every solver matches every reference.
- **Deferred**: interpolation between different time grids (same-length columns only, as the platform; the generic
  solvers and the references share the SED-ML grid), and reimplementing `/curated/copasi|tellurium` on this path
  (their cluster tests compare today's outputs; the SED-ML path makes them redundant rather than wrong).
- CLI: `biomodels search|show|get|run`, `biosimulations search|show|get|reference|run`.

## Phase 5: what exists after it

- **`/ui/sedml`**: an archive from three places (an upload, a BioModels search, a biosimulations.org search; or
  `?source=biomodels:ID` / `biosimulations:ID`), its translation previewed (each task, the solvers that accept it
  and those refused, the findings, the `.pblang` template), then solvers, tags and a description chosen, and Run,
  which opens the comparison. A BioModels or biosimulations.org source runs through its shortcut, so its runs are
  labelled with it and a project's original results become the reference (`SedmlRunPanel.vue`, `useSedml.ts`).
- **`/ui/comparisons`, `/ui/comparisons/{id}`**: the verdict (the solvers agree or differ; whether they match the
  original results), the runs, a score matrix per report (data sets by solver and reference pairs, close in green,
  far in red, the worst named), one data set from every run and reference overlaid
  (`GET /comparisons/{id}/series?report=`), and each SED-ML plot with every run's traces overlaid, dashed per solver.
  It refreshes while the runs are going.
- **A Plotly viewer** for figure datasets (`*.plotly.json`) on any run's page.
- Checked in headless Chrome against the API answered with data made by the real code: the Ciliberto project's
  translation, COPASI and Tellurium outputs from biosim-toolkit's steps, and `compare()` against the project's
  original Tellurium 2.2.1 results. The solvers agree with each other and with the original results (worst score
  0.02, Cdh1).

## Phase 6: what exists after it

- **Suites** are `examples/<name>/suite.yaml` (`compose_api/sedml/suites.py`): sources (`biomodels:<id>`,
  `biosimulations:<project>`), solvers, tolerances, expected failures (with reasons) and the accepted `baseline` run.
  Two seeds, chosen by translating candidates on both solvers:
  - `biomodels-ode-sample`: twenty curated ODE BioModels entries (of BIOMD0000000001-60, 56 translate on both
    solvers; BIOMD0000000005 has no SED-ML, BIOMD0000000042 asks for a non-ODE algorithm, BIOMD0000000036 was
    unavailable);
  - `biosimulations-reference`: ten biosimulations.org projects whose original runs used different simulators
    (Tellurium, COPASI, AMICI, PySCeS), each compared with its original results.
  - `smoke`: two models (BIOMD0000000012, the Ciliberto project with its original results), the quick end-to-end
    check after a release or an environment change.
- **A suite run** (`POST /suites/{name}/run`, `compose_api/sedml/suite_runs.py`) gets the next number, then fetches,
  translates and submits every source in the background: one comparison per source and task, labelled
  `collection=<suite>` and `suite_run=<n>` (columns `comparison.collection`, `comparison.suite_run`, migration
  `7c2d4e9a1b38`; table `suite_run` with the sources that could not be submitted and why).
- **Reading a run** (`GET /suites/{name}/runs/{n}`): per source and task, whether the solvers agree, whether they
  match the references, the worst data set, and, once the suite has a baseline run, each solver's **drift**: its
  report scored against its own report in the baseline run (same score and tolerances). Expected failures are shown
  as such. `GET /suites`, `GET /suites/{name}/runs`.
- **Scheduled**: `.github/workflows/sedml-suites.yml` runs every suite on the deployed service on the first of each
  month and on demand; the job summary links each run's page. A new baseline is accepted by a pull request setting
  `baseline` in the suite's file.
- **Web app**: `/ui/suites`, `/ui/suites/{name}` (runs, and for one run a row per model: agreement, references,
  worst data set, drift per solver, notes; "Run the suite"). CLI: `suites list|runs|show|run`.
- An archive without SED-ML is now refused with that reason.

## Data model (phase 0, phase 3)

- `simulation`: `labels` JSONB (written by the service, reserved keys above), `tags` text[] and `description` (given
  at submission). `GET /simulations?label=key:value&tag=…`, with a GIN index.
- `comparison`: id, name, source reference, settings (tolerances), status, result JSONB, created_at.
- `comparison_member`: comparison, simulation, solver. `comparison_reference`: comparison, dataset, origin.

## API (phases 0, 3, 4)

- `POST /sedml/run`: an `omex` upload **or** `source=biomodels:<id>|biosimulations:<project>`, `solvers[]`,
  optional `task`, tolerances, `tags[]`, `description`. Returns `{comparison_id, simulations[], refused[]}`.
- `POST /sedml/preview`: the translation's tasks, reports, plots and findings per solver, without running.
- `GET /comparisons?label=…`, `GET /comparisons/{id}`, `GET /comparisons/{id}/result.{json,csv}`.
- Sources, read-only, archives cached in the object store by id and upstream version:
  `GET /sources/biomodels/search?q=`, `GET /sources/biomodels/{id}`, `GET /sources/biomodels/{id}/omex`;
  `GET /sources/biosimulations/projects?q=`, `GET /sources/biosimulations/{project}`, `…/{project}/omex`,
  `…/{project}/reference`; and `POST /sources/{biomodels|biosimulations}/{id}/run`.
- `GET /registry/entries`, `GET /registry/solvers`.
- `/curated/copasi` and `/curated/tellurium` become an SBML-only uniform time course through the same path, which
  retires their Jinja templates.

## Suites (phase 6)

`examples/<suite>/suite.yaml`: sources (BioModels ids, biosimulations.org projects, optionally per task), solvers,
tolerances, expected failures with reasons, and the accepted baseline run. A suite run is a set of comparisons
labelled `collection` and `suite_run`, and checks two things:

- **agreement**: the solvers with each other and with the references;
- **regression**: each solver against its own result in the baseline run, by the same score, so a new image digest,
  solver version or translator version that changes a result shows even when the solvers still agree.

A workflow reruns suites monthly and when `environments.yaml`, `solvers.yaml` or the process-bigraph-lang pin
changes. A new baseline is accepted by a pull request to `suite.yaml`. Seeds: `biomodels-ode-sample` (about twenty
curated ODE models with a uniform time course) and `biosimulations-reference` (projects whose original run has
results).

## Web app (phase 5, phase 6)

`/ui/sedml/new` (upload or source, preview, choose solvers, run), `/ui/sources` (search, a model page, "Run on…"), a
Plotly viewer for figure datasets, `/ui/comparisons/{id}` (a matrix per report with the worst variable; each SED-ML
plot drawn once with every member's traces and the reference; per-variable overlays and differences; links to the
member runs), `/ui/suites` and `/ui/suites/{name}` (models by solvers per run, agreement and drift, history), label
and tag filters on `/ui/simulations`, and `/ui/catalog` on `/registry/entries`.

## Verification

- process-bigraph-lang: each corpus SED-ML (BIOMD0000000012, the Ciliberto 2003 morphogenesis project, two more) is
  described, templated, checked and compiled per solver to a snapshot; a solver lacking the role is refused;
  out-of-scope SED-ML is reported; plot filling is tested against a known CSV.
- This service: `make check`, `make test`; the score against the platform's fixture values; the source routes
  against recorded archives.
- On the cluster: BIOMD0000000012 on COPASI and Tellurium gives two labelled runs with both archives, report CSVs and
  figures, and one comparison scored per variable; the Ciliberto project is compared against its original results,
  its plots overlaid; a two-model suite run twice shows no drift, and a tightened tolerance shows a failure.

### On the cluster, 2026-10-13 (compose-api 0.7.21)

The first attempts (0.7.19, 0.7.20) never ran: the shared image could not be built on the cluster, which
`docs/plan-environment-builds.md` fixed (the image is now built as a Kubernetes Job).

- **Ciliberto project** (comparison 3): COPASI and Tellurium agree, and both match the original Tellurium 2.2.1
  results; worst data set SBF, score 0.019.
- **BIOMD0000000012** (comparison 4): the solvers agree, worst Y, 0.059. The same archive with `rel_tol=1e-12`
  (comparison 5) differs, as it should.
- **Suites, run 1** (now each suite's baseline):
  - `smoke`: 2 of 2 agree.
  - `biomodels-ode-sample`: 14 of 20 agree.
  - `biosimulations-reference`: 6 of 10 agree; every completed solver matches the original results except Tellurium
    on the Edelstein model.
- **Findings, recorded as the suites' expected failures, all in the solver steps (pbsim-common 0.1.2):**
  - The Tellurium step writes every species back into RoadRunner each update, and RoadRunner refuses a species
    defined by an assignment rule. Six runs fail this way: BIOMD 7, 9 and 16, and three biosimulations.org projects.
  - Tellurium disagrees on the Edelstein event model (BIOMD0000000001 and the Edelstein project), where COPASI
    matches both original results.
  - The COPASI step fails on a model without species (BIOMD0000000020, Hodgkin–Huxley: rate rules only).
  - BIOMD0000000043: the solvers differ on Rho (score 6.5); there is no reference, and it is not investigated yet.
- **Drift:** `smoke` run 2 against its baseline is to come.

## Out of scope

Steady state, repeated and nested tasks, math in data generators, SED-ML plots in 3D beyond surfaces; solvers beyond
COPASI and Tellurium (AMICI, VCell and the BioSimulators images need their own environments: strategy.md decision 5,
phase D); owner-editable tags; rendering Vega specs shipped in project archives (they are listed as files).
