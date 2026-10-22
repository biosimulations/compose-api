# TR&D3 Year 3 progress: outline

**Period.** Grant Year 3, 1 April 2026 – 31 March 2027. Accomplishments are to 13 October 2026; plans run to March
2027. The Year 2 report (period to 31 March 2026) already covered October 2025 – March 2026, which appears here only as
context.

**Scope.** All of TR&D3: compose-api and its web app, process-bigraph-lang, the BioSimulations platform, pbest,
viva-pde-particle and the other `viva-*` wrappers, process-bigraph and Vivarium, SED2, and the BioModels collaborating
project.

**Status.** This is an outline for the Year 3 progress report and the advisory-board talk
([Y3-deck-storyboard.md](trd3-y3-deck-storyboard.md)). Statuses come from [TRACKER.md](grant/trd3/tracking/TRACKER.md) (refreshed
2026-10-13), and deviations come from [DEVIATIONS.md](grant/trd3/tracking/DEVIATIONS.md). Items marked **[to fill]** need a
person: they cannot be settled from repositories.

**Structure.** Sections 1–7 follow the progress report's sections B.2, B.4, B.5, B.6 and C. Within TR&D3 it uses the
bold subheads TR&D1 used in Year 2, so that each section can be lifted into the report.

---

## 1. Summary (one paragraph in the report)

In Year 3, composition moved from a prototype to a production service. Composite simulations are:

- written in a checked language;
- verified against the interfaces of the environment they will run in;
- executed on HPC from images pinned by digest;
- observable while they run;
- compared, solver against solver and against published results, on a schedule.

The Year 2 report made three forward commitments, and SED2 is a fourth:

| Year 2 commitment | Status, 2026-10-13 | Where |
|---|---|---|
| Validate the Composition API through real composites with collaborating projects and at HPC scale | **Met at HPC scale.** The collaborating-project half is under way (BioModels with Sego) | §2A, §3 |
| Expand the process registry with spatial and particle-based tools | **Met:** ReaDDy, viva-pde-particle; registry with curation levels | §2D |
| Begin an adapter registry (units, concentrations↔counts) | **Not yet begun as a registry**; planned for Q4 2026 | §6 |
| Roll out SED2 v1 ("the biggest project for TR&D3") | **[to fill]:** working-group status, HARMONY 2026 demo | §2F |

## 2. Accomplishments (B.2)

Each subsection gives what was done, then its evidence. The aim and task numbers are the grant's.

### A. The Composition API, validated at HPC scale (Aim 3, Task 3.2; goals G2, G3, G6)

- **Production service.** compose-api runs at <https://compose.cam.uchc.edu>.
  - It went from release 0.4.0 (Apr 2026) to 0.7.25 (13 Oct 2026).
  - It runs on the RKE Kubernetes cluster, which submits to the Mantis SLURM cluster under a service account, with
    storage on `/projects/CRBM` (#115, #116).
  - Deploys are GitOps through Flux (#239), and each monthly release is archived on Zenodo (concept 21127421, #119).
- **Scale.** There have been 4,428 runs since 1 April 2026: 3,447 completed and 981 failed (live service,
  2026-10-13). This includes a batch campaign of about 3,570 runs in May 2026 (batch processing, #104).
- **Reproducible by construction (G3).**
  - Environment images are pinned by digest.
  - Every run records its image and the checksums of its outputs.
  - Environment images are built as artifacts of their own, in Kubernetes Jobs or on SLURM, joined rather than
    duplicated. See [plan-environment-builds.md](plan-environment-builds.md), #292–#299.
  - The first Kubernetes build ran on 2026-10-13 (`registry_env`, 936 MB).
- **Safe by construction (G6, met 2026-10-06).**
  - A submission that names an unregistered process address is refused with a clear message (0.6.0, #184).
  - A registry manifest assigns each component a curation level.
- **Observable.**
  - Each run's events, its trace (opened directly in Perfetto, #304) and its datasets are recorded. Datasets include
    the input, logs, tables, figures, zarr and directory outputs, and 3D results viewed in the browser. See
    [plan-observability.md](plan-observability.md) and [plan-viewers.md](plan-viewers.md),
    #204–#222 and #241–#244.
  - Runs carry labels, tags and descriptions for query (#283).
- **Scriptable (Aim 3, Task 3.3b).** `compose-api-client` is on PyPI with a CLI covering every API operation (0.7.0,
  [plan-cli.md](plan-cli.md)).
- **Also from Valencia's pbest (Nov 2025 – May 2026):** a composite builder, HPC submission, containerization, and
  releases 0.3.1–0.6.3.

### B. A checked composition language and authoring (Aim 2, Task 2.1; Aim 3, Task 3.3a static checker)

- **process-bigraph-lang `.pblang` v2.** A textual, verifiable projection of the process-bigraph composite document. It
  covers interfaces, wiring, templates with open sites, units and SBML model headers. See
  [design](https://github.com/biosimulations/process-bigraph-lang/blob/main/docs/v2/design.md).
  - One Langium grammar and checker serve the CLI, the language server and the browser.
  - It compiles to and decompiles from `.pbg` documents and CompositeSpec YAML.
  - Releases 0.1.0–0.3.1 (12–13 Oct 2026) are on PyPI (wheels for each platform) and npm.
- **The static checker the grant names for Year 1 (tracker A3.3a, now `delivered?`).** It reports coded diagnostics:
  unknown ports, wire-type mismatches, missing config, conflicting writers, unit mismatches and template-site fills.
- **Interface manifests (`pbg-interfaces/1`).**
  - The format is shared and versioned, with a JSON Schema (process-bigraph-lang #56).
  - A manifest is generated inside each environment's image (#270) and served at `/registry/environments/{name}`.
  - Each environment's classes are also available as `.pblang` headers (#306).
- **Authoring in the browser (Aim 1, Task 1.4).** In the web app, a user writes a composite and it is checked as they
  type against the environment it will run in. Run then submits it (#263, #271, #272, #280).

### C. Reproducibility and credibility through multiple solvers (Aim 1, Tasks 1.1 and 1.3)

- **SED-ML on several solvers.** A SED-ML archive from BioModels, from biosimulations.org or uploaded is processed in
  three steps:
  1. it is translated into a `.pblang` template with the solver left as an open site;
  2. it is checked for each solver against that solver's interface;
  3. it is run once per solver (COPASI and Tellurium), with the runs grouped in a comparison.

  Reports and Plotly figures come out of the composite itself. See [plan-sedml.md](plan-sedml.md),
  #282–#289, and process-bigraph-lang #57–#60.
- **Comparison.**
  - It uses the BioSimulations verification score, per report and variable, solver against solver and against the
    original published results.
  - To date: 39 comparisons, 30 complete.
  - The Ciliberto et al. 2003 project matches its original results (worst score 0.019).
  - BIOMD0000000012 (repressilator) agrees across solvers.
  - The same archive with tightened tolerances correctly fails.
- **Regression and reproducibility suites** (`examples/<suite>/suite.yaml`).
  - Each suite has a baseline, expected failures with reasons, and drift detection, and is rerun monthly by a
    scheduled workflow.
  - Baselines: `smoke` 2/2, `biomodels-ode-sample` 14/20, `biosimulations-reference` 6/10.
  - The second run of `smoke` shows no drift from its baseline.
- **Credibility catches real defects.**
  - The suites traced most disagreements to the solver *steps*, not the models: Tellurium writing back species that
    are defined by assignment rules, Tellurium's handling of events, and COPASI on a model with no species.
  - One disagreement (BIOMD0000000043) remains uninvestigated.
  - This answers the Year 1 board's warning to attribute failures carefully.
- **The BioSimulations verification paper.** Smith LP, …, Schaff JC, Agmon E, Patrie AA, …, Sauro HM, *PLoS Comput
  Biol* 2025;21(12):e1013239. It verified 1,073 BioModels entries on five simulators. This is Year 2 work, published in
  Year 3; **[to fill]** the TR&D1 follow-up paper on the verification API.

### D. Process registry: spatial and particle-based tools (Aim 1, Task 1.2; Aim 4, Task 4.1; goal G4)

- **ReaDDy (particle-based).** In the shared image and runs on HPC (tracker A1.2.readdy, delivered in August 2026).
- **viva-pde-particle (spatial plus particle hybrid).**
  - Smoldyn particles are co-simulated with PDE solvers (finite volume, FEniCSx, VCell geometry).
  - It is benchmarked against the hybrid solver inside `vcell-fvsolver`.
  - It reproduces Schaff et al. 2016, Tests 1–5.
  - It runs in production from its own image. Its 138-job ensemble on Mantis reproduced the local metrics exactly.
  - Tracker A4.1.particle-pde is now `delivered?`.
- **Registry and catalog.**
  - The catalog has 52 registry entries (48 `listed`, 4 `tested`).
  - There are two environments (`registry_env`: 15 components, 0 import errors; `viva-pde-particle`).
  - There are two SED-ML solvers.
  - Each environment has an interface manifest, and the web app has catalog and environment pages
    (`/registry/entries`, `/ui/environments`).
- **Wrappers, mostly Agmon's group (D3).** `viva-*` processes for MEDYAN, Mem3DG and cellPACK are in progress;
  cellular Potts (`viva-cpm`, Artistoo, CC3D) is delivered; Cahn-Hilliard is in progress. **[to fill]**: confirm the
  status of each for Year 3.

### E. The BioSimulations portal (Aim 1, Tasks 1.1 and 1.4)

- **The BioSimulations platform (Burr).** It is being rebuilt as a monorepo deployed on GKE at
  <https://biosim.biosimulations.org>.
  - Features: project search with KiSAO facets, run pages, rerun, Auth0 login, and validation of models, metadata and
    projects.
  - Latest releases: backend 0.10.1, frontend 0.3.6 (13 Oct 2026).
  - **[to fill]:** beta usage numbers.
- **The composition front end** is compose-api's `/ui`: dashboard, runs, datasets and viewers, the composite editor,
  SED-ML runs, comparisons and suites.
  - Deviation D2: composites run on compose-api, not runBioSimulations.
  - Goal G7 still needs a dated decision on whether the two front doors converge.

### F. Standards (Aim 2, Task 2.2; Aim 1, Task 1.1, SED)

- **SED2 working group.** Co-led by Agmon (TR&D3) and Smith (TR&D1); 25 members; meets monthly. **[to fill]:** whether
  the HARMONY Feb 2026 demo happened, and the first version's status.
- **The process-bigraph composition format.** Described in arXiv:2512.23754 (preprint, Year 2). **[to fill]:** journal
  status.
- **Machine-readable interface format (`pbg-interfaces/1`)** and the `.pblang` language: a human-readable half of the
  protocol specification that D1 still owes.

## 3. Collaborating and service projects

- **BioModels (T.J. Sego, University of Florida; with Agmon). This is the collaborating project for goal G1.**
  - BioModels entries run on this service by id, on two solvers, compared against each other.
  - The `biomodels-ode-sample` suite is the seed of corpus-wide agreement. **[to fill]:** the state of the
    collaboration, and whether Sego's group has run one end to end.
- **Simularium (Allen Institute for Cell Science), CP4.** ReaDDy is delivered and MEDYAN is in progress; cellPACK
  versus parsimony and Cytosim are still open decisions.
- **DARPA Simulating Microbial Systems.** Its composite format and kernel are aligned with this work (Year 2 report).
- **CP9, digital twins.** `viva-uq`, `viva-ketchup` (parameter estimation) and the parameter scans in pbest.
- **[to fill]:** CP1 (Cell Collective), CP6 (Synthetic Cells), CP7 (SASCO) and CP10 (cell-free/NIST). The tracker
  has no evidence for any of them.

## 4. Training and dissemination (B.4 and B.5)

The Year 2 response to the board said TR&D3, apart from Agmon, does not contribute to dissemination. Year 3's answer
is in evidence:

- **Public, documented services:** API docs at `/docs` and a full CLI reference
  ([cli.md](cli.md)).
- **Packages:**
  - compose-api-client on PyPI;
  - process-bigraph-lang on PyPI and npm (an embeddable editor for other web apps);
  - pbest on PyPI.
- **Archiving:** monthly Zenodo rollups with DOIs.
- **Design documents in the open:** the `docs/plan-*.md` files, the CIP design review, and process-bigraph-lang
  `docs/v2/`.
- **[to fill]:**
  - talks at IMAG, COMBINE 2026 and HARMONY 2026, and posters;
  - the summer schools (2026, organized with T&SD1);
  - SED2 meetings;
  - who presented each.

## 5. Deviations, overdue items and risks

- **D1. The protocol exists as code, not a written specification.** Still owed: a versioned `CIP-spec` and a
  COMBINE/HARMONY presentation. `.pblang` and `pbg-interfaces/1` now give it a checkable, human-readable form.
- **D2. Composites run on compose-api, not runBioSimulations.** Still owed: the G7 decision.
- **D3. New simulators are `viva-*` processes, not BioSimulators containers.** Still owed: a catalog of every wrapper
  at its measured curation level.
- **Overdue:**
  - ODE/SSA and FBA/Boolean templates (due Year 2, not started);
  - Cytosim (not started);
  - a collaborator's execution engine (A3.2.engines, not started);
  - processes in separate containers within one composite (A3.4.docker).
- **External:** the credibility portal (Year 3–4) depends on TR&D1's credibility libraries (A1.3.cred, blocked).
- **Operational:**
  - Submissions in flight when the API restarts are lost (#238; a durable-queue plan is #258).
  - pbest 0.6.x on PyPI fails on bare `.pbg` documents; worked around in 0.7.25 (#308).

## 6. Plans for the rest of Year 3, to March 2027 (B.6)

Each item names the goal or tracker row it closes; dates are targets **[to confirm]**.

| By | Item | Closes |
|---|---|---|
| Nov 2026 | Adapter registry: an `adapter` category in the registry manifest, seeded with counts↔concentrations and unit conversion; one composite using it | G5, A3.3e (Year 2 commitment 3) |
| Nov 2026 | Fix the solver-step defects the suites found upstream (pbsim-common), rebuild the image, rebaseline | A1.3.verify |
| Dec 2026 | ODE/SSA and FBA/Boolean templates as `.pblang` templates with open sites, run on the service | A4.1.ode-ssa, A4.1.fba-bool |
| Dec 2026 | BioModels: corpus-wide agreement across solvers on the service; Sego's group runs one composite end to end and writes the walkthrough | G1, CP-BM |
| Jan 2027 | One SED2 document executed through the service, or a dated note saying why not | A1.1.sed |
| Feb 2027 | A versioned CIP specification (process interface, composite document, orchestration) with `pbg-interfaces/1`; presented at HARMONY 2027 | D1, A2.spec |
| Mar 2027 | A decision on the two front doors (platform and compose-api) | G7, D2 |
| Mar 2027 | Credibility portal started with TR&D1, or recorded as blocked | A1.3.cred |
| ongoing | Environment builds phase 5 (publish to a registry); durable submissions (#258) | G3, G2 |

## 7. Products (C.2 and C.3)

Count tools delivered and maintained, not repositories. The toolchain was consolidated on purpose; see
[goals.md §4](goals.md).

| Product | Kind | Version / URL |
|---|---|---|
| Compose API | service | <https://compose.cam.uchc.edu> (0.7.25), `/docs`, `/ui` |
| BioSimulations platform | service | <https://biosim.biosimulations.org> (backend 0.10.1, frontend 0.3.6) |
| compose-api-client | Python package and CLI | PyPI |
| process-bigraph-lang | language, checker, editor | PyPI and npm 0.3.x |
| pbest | composite builder, HPC submission | PyPI 0.6.3 |
| biosim-toolkit | SED-ML adapter steps | in `registry_env` |
| viva-pde-particle | hybrid PDE/particle environment | prebuilt image on the service |
| process-bigraph, bigraph-schema | orchestration engine, type system | PyPI (process-bigraph 1.8.x, bigraph-schema 1.7.x) |

## Numbers (live service, 2026-10-13)

Re-query these on the day; each comes from a public `GET` on <https://compose.cam.uchc.edu>.

| Number | Value | Query |
|---|---|---|
| Runs since 2026-04-01 | 4,428 (3,447 completed, 981 failed) | `/simulations?since=2026-04-01T00:00:00Z[&status=…]` → `total` |
| SED-ML runs | 76 (46 from BioModels, 30 from biosimulations.org) | `/simulations?label=source:biomodels`, `…:biosimulations` |
| Comparisons | 39 (30 complete) | `/comparisons?limit=100` |
| Registry entries | 52 (48 listed, 4 tested) | `/registry/entries` |
| Environments, components | 2; `registry_env` 15 components, 0 errors | `/registry/environments` |
| SED-ML solvers | 2 (COPASI LSODA, Tellurium CVODE) | `/registry/solvers` |
| Merged PRs, 2025-10 to 2026-10 | compose-api 177, platform 95, viva-pde-particle 58, pbest 22, process-bigraph-lang 18 | `gh pr list --state merged` |
