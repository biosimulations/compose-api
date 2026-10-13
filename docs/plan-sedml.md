# SED-ML models as process-bigraph runs across solvers, compared

**Status (2026-10-12): plan agreed; phase 0 in review.** One PR per phase and repository, merged with a merge commit on
the maintainer's word; each PR updates the table below. A merge deploys nothing by itself: the next release's image
ships it (CLAUDE.md, "Deploys are GitOps"). The language side is planned in process-bigraph-lang's
[`docs/v2/sedml-plan.md`](https://github.com/biosimulations/process-bigraph-lang/blob/main/docs/v2/sedml-plan.md).

| Phase | What | Repo | State |
|---|---|---|---|
| 0 | Labels, tags and a description on simulations, and filters on them; the concepts below documented; `GET /registry/entries` and `/ui/catalog` rebuilt on it | compose-api | in review |
| 1 | SED-ML read into a `.pblang` template per task with the solver as an open site, one checked instance per solver; plots built at run time; release 0.3.0 | process-bigraph-lang | in review (#58, #59) |
| 2 | SED-ML adapter steps around generic COPASI and Tellurium steps; `solvers.yaml` and `GET /registry/solvers` | adapters package, compose-api | planned |
| 3 | `POST /sedml/run` and `/sedml/preview`; the `sedml-omex` and `input` datasets; comparisons computed on the server; references | compose-api | planned |
| 4 | BioModels and biosimulations.org source routes, cached; run shortcuts; the curated routes on the same path | compose-api | planned |
| 5 | Web app: ad-hoc SED-ML page, sources, a Plotly viewer, the comparison page | compose-api `webapp/` | planned |
| 6 | Regression and reproducibility suites, rerun on a schedule, with their pages | compose-api | planned |

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

## Out of scope

Steady state, repeated and nested tasks, math in data generators, SED-ML plots in 3D beyond surfaces; solvers beyond
COPASI and Tellurium (AMICI, VCell and the BioSimulators images need their own environments: strategy.md decision 5,
phase D); owner-editable tags; rendering Vega specs shipped in project archives (they are listed as files).
