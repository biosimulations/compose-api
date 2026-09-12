# TR&D3 grant tracker

Tracks what the funded TR&D3 documents promise against what exists, one row per atomic commitment. The grant is not a
contract: the intent is to deliver the majority of items, and where we deviate, to deliver in spirit and say why in
[DEVIATIONS.md](DEVIATIONS.md). Grant text lives in `../` (git-ignored); quotes below are taken from
`TR&D3 - Research Strategy.md` unless noted.

**Grant clock.** Project period 03/01/2024 – 02/28/2029. Y1 = Mar 2024–Feb 2025 · Y2 = Mar 2025–Feb 2026 ·
**Y3 = Mar 2026–Feb 2027 (now)** · Y4 = Mar 2027–Feb 2028 · Y5 = Mar 2028–Feb 2029.

**Status legend.** `not-started` · `in-progress` · `delivered` · `in-spirit` (delivered in a different form, see
DEVIATIONS) · `deviated` (consciously replaced or descoped, see DEVIATIONS) · `dropped` (see DEVIATIONS) ·
`blocked-external` (waiting on TR&D1, TR&D2, or a CP). A trailing `?` means the status was inferred from repository
evidence on 2026-09-09 and has not been confirmed by a person.

**Kind.** `infra` software we build · `standard` a specification or format · `science` a modeling result ·
`collab` a push/pull with a CP or another TR&D · `community` meetings, hackathons, standards bodies.

**Evidence sources.** GitHub orgs `biosimulations`, `biosimulators`, `vivarium-collective` (plus `cam-center` and
`virtualcell` where a named simulator lives there). Repo names are `org/repo`; dates are last push as of 2026-09-09.

## Roll-up (2026-09-09, statuses verified against GitHub)

| Status | Rows | of which `?` (inferred, unconfirmed) |
|---|---|---|
| delivered | 7 | 0 |
| in-spirit | 6 | 0 |
| in-progress | 24 | 1 |
| deviated | 1 | 0 |
| not-started | 6 | 0 |
| blocked-external | 1 | 0 |
| unknown (`?` only, needs a person) | 5 | 5 |
| **total** | **50** | **6** |

The six remaining `?` cannot be settled from code: A3.x.steer, and the five community/collaboration rows
(A4.3.imag, A4.3.combine, CP1, CP7, CP10). A GitHub search cannot disprove an unrecorded collaboration, so those
need email, subaward, or progress-report evidence.

**Overdue or due now (Y1–Y2 promises not yet `delivered`/`in-spirit`):** A2.spec (Y1) · A3.2.engines (Y1) ·
A3.3a (Y1) · A3.3e (begin Y1) · A4.1.ode-ssa (Y2) · A4.1.fba-bool (Y2) · A1.4 (Y2–3) · A1.2.cytosim,
A1.2.cahn, A1.2.springsalad (Y1–3).

**Not started anywhere:** A1.2.cytosim · A3.2.engines · A4.1.ode-ssa · A4.1.fba-bool · A4.3.syncell · CP6.
A2.spec (the consolidated protocol specification) is the item that makes Aim 2 a *standard* rather than a codebase;
it is partially written.

**Cheapest high-value moves**, from the verification pass: the two missing Y2 templates (ODE/SSA, FBA/Boolean) both
have all their component processes already wrapped, so each is a wiring exercise plus the counts↔concentrations
adapter that A3.3e needs anyway. One composite with processes in two containers closes A3.4.docker. One `viva-tellurium`
to `viva-fenics` wiring closes A4.1.ode-pde.

---

## Aim 1. BioSimulations 2.0: an expanded web portal for credibility and composition

### Task 1.1 Populate BioSimulations with more published simulations

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A1.1 | Many more published simulations in a publish/browse/search database; deposit tooling for developers and model repositories | infra + collab (TR&D2 curation) | Y1–5 | in-progress | `biosimulations/biosimulations` v9.65.4 · `biosimulations-bigg` 0.0.5 · `biosimulations-modeldb` 0.0.4 · `biosimulations-runutils` 0.1.0 · `biomodels-qc` 0.0.3 · `biomodels-regression` · `vivarium-collective/biomodels-comparison` (892 BioModels, multi-simulator) | Record current project count vs. the "500 + 1000 expected" baseline; confirm whether TR&D2 semantic search is wired in |
| A1.1.sed | "Revisit SED-ML as proposed to develop the next generation of the simulation description language" | standard | Y1–5 | in-progress | `biosimulations/sed` (Aug 2026, "new SED standard") · `biosimulators/bscose` (SED2 builder) · `vivarium-collective/sed2` (2023) | Decide whether SED2 goes to COMBINE as a proposal; link to A2.2 |

<details><summary>Grant wording</summary>

"We will use the database of simulation runs developed in the first cycle to build a database for publishing,
browsing, and searching simulations. Enhanced search capabilities will be implemented using the semantic tools
developed in TR&D2. […] We will also work with simulation software developers and model repositories to make it easy
for investigators to deposit simulations to this database. In the process of doing this work we will also revisit
SED-ML as proposed to develop the next generation of the simulation description language." Milestone (3): "Expanded
simulation database: many more published models will be added, and linked to credibility (years 1-5)."
</details>

### Task 1.2 Add more simulators

The grant says "containerize and validate more simulators" into the BioSimulators registry. What has actually been
built is process-bigraph wrappers (`viva-*`) that expose each simulator through the Aim 2 process interface. That is
the more useful form for Aims 3–4 and is recorded as [D3](DEVIATIONS.md#d3) rather than as a miss.

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A1.2.springsalad | SpringSaLaD (particle-based mesoscopic dynamics) | infra + collab | Y1–3 | in-progress | `cam-center/SpringSaLaD` and `cam-center/LangevinNoVis01` active (Aug 2026); no `viva-springsalad` or BioSimulators container found | Wrap the headless Langevin solver as a process |
| A1.2.cytosim | Cytosim (mesoscale actin) | infra + collab (CP4) | Y1–3 | not-started | only `vivarium-collective/vivarium-cytosim` (2022, Vivarium 1) | Decide: port to process-bigraph, or drop in favour of MEDYAN + ReaDDy (see D3) |
| A1.2.medyan | MEDYAN (mesoscale actin) | infra + collab (CP4) | Y1–3 | in-progress | `vivarium-collective/viva-medyan` (Jul 2026; pure-Python re-implementation + subprocess bridge) | Validate against upstream MEDYAN output |
| A1.2.mem3dg | Mem3DG (deformable membranes) | infra + collab | Y1–3 | in-progress | real `pymem3dg` bridge (`pbg_mem3dg/processes.py` drives `dg.System`/`dg.Euler`), but smoke tests only and no CI; `viva-membrane-actin-composite` grades itself "WORKFLOW-READY, NOT YET VALIDATED" and its per-vertex force coupling is blocked by a pymem3dg segfault | Add a validation case against a Mem3DG reference; chase the upstream applied-force segfault |
| A1.2.cellpack | cellPACK (molecular structures) | infra + collab (CP4) | Y1–3 | in-progress | `vivarium-collective/viva-cellpack` (May 2026) · alternative packing engine `parsimony` / `viva-parsimony` / `3d-ecoli` (Aug 2026) | Decide whether parsimony supersedes cellPACK (in-spirit candidate) |
| A1.2.readdy | ReaDDy (nanometer-scale filaments, motors) | infra + collab (CP4) | Y1–3 | delivered | `vivarium-collective/viva-readdy` (Aug 2026) · runs on HPC via this repo, `tests/simulators/test_readdy.py` | — |
| A1.2.cpm | A cellular Potts model (CC3D, Morpheus, Artistoo, or compatible) | infra + collab | Y1–3 | delivered | `viva-cpm` (own Rust engine) reproduces Glazier & Graner 1993 across 11 completed studies and benchmarks at parity with CompuCell3D 4.10 · `viva-artistoo` drives real Artistoo with sorting/checkerboard behaviour tests (Node-gated) · `viva-compucell3d` is a real CC3D wrapper, smoke tests only | Morpheus not wrapped; optional |
| A1.2.cahn | A Cahn-Hilliard PDE solver | infra | Y1–3 | in-progress | `meta-modelers-guide` ships `composites/condensate-cahn-hilliard.composite.json` with `tests/test_cahn_hilliard.py` · adjacent PDE processes: `viva-fenics` (real dolfinx), `viva-vcell-fvsolver`, `virtualcell/vcell-mbsolver` | Promote the condensate composite into a named solver/template, or record FEniCS as the substitute |

<details><summary>Grant wording</summary>

"To support additional simulation algorithms, we will continue to work with CPs and SPs and other external
collaborators to containerize and validate more simulators. This includes SpringSaLaD for particle-based mesoscopic
dynamics, Cytosim and MEDYAN for mesoscale actin simulations, Mem3DG for deformable membranes, cellPACK for molecular
structures, ReaDDy for nanometer-scale models of actin filaments, microtubules, and cytoskeletal motors, a cellular
Potts model either from CC3D, Morpheus, Aristoo, or other compatible simulator, a Cahn-Hilliard PDE solver, etc."
Milestone (2): "we will work with CPs to add several popular simulators including SpringSaLaD, Cytosim, ReaDDy, MEDYAN,
and Mem3DG (one at a time, years 1-3)."
</details>

### Task 1.3 Credibility portal

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A1.3.verify | Verification side: check simulations across simulators, link each study to a report | infra | Y3–4 | in-progress | `biosimulations/platform` = "Biological Simulation Verification Service (BSVS)", `biosim.biosimulations.org`, frontend-v0.2.2 (Sep 2026) · `biosimulators/bsvs` client · `biomodels-comparison` · `viva-uq` (PCE + Sobol UQ) | Define what the BSVS report covers vs. the grant's "credibility report" |
| A1.3.cred | Credibility side: drag-and-drop model → report from TR&D1 Aim 3 libraries (IMAG ten rules, biophysical soundness, validation tests) | infra + collab (TR&D1) | Y3–4 | blocked-external | no TR&D1 credibility library integration found in any org | Ask TR&D1 what library exists; BSVS is the natural host |

<details><summary>Grant wording</summary>

"We will develop a separate web portal where users can drag and drop their models to obtain a credibility report
describing all features and missing points. […] The credibility portal will be a front end for the credibility
libraries developed by TR&D1's Aim 3, including tests listed in the IMAG ten rules for model credibility as well as a
suite of more fine-grained tests such as biophysical soundness, simple errors in the model, validation tests and
verification test." Milestone (1): "Credibility portal: a new web portal for verifying model credibility using
libraries developed by TR&D1 (years 3-4)."
</details>

### Task 1.4 Web-based composition app

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A1.4 | Web page to build composite simulations from the Aim 2 standard with Aim 3 tools; composite results stored alongside single-simulator runs | infra | Y2–3 | in-progress | `vivarium-collective/vivarium-workbench` v0.3.56 (Sep 2026) · `viva-catalog` ecosystem ledger · `vivarium-guide` · backend `viva-api` (sms.cam.uchc.edu) and this repo (compose.cam.uchc.edu) | Decide whether the workbench *is* the portal or feeds `biosimulations/platform`; see [D2](DEVIATIONS.md#d2) |
| A1.4.onboard | "Simplify the onboarding of new Biosimulators and automatically include the process interface" | infra | Y2–3 | in-spirit | `viva-template` scaffold + `viva-superpowers` / `pbg-superpowers` skills generate a wrapped Process; `viva-catalog` auto-discovers repos by GitHub topic | Not automatic from `biosimulators_utils`; see D3 |

<details><summary>Grant wording</summary>

"BioSimulations 2.0 will include a web page that allows users to build composite simulations via a simple web
interface that works with the composition standard introduced by Aim 2, with composition tools built by Aim 3. We will
simplify the onboarding of new Biosimulators and automatically include the process interface […]. The results of
composite simulations will be saved in the same BioSimulation repository that currently holds simulations of single
simulators." Milestone (4): "Composition portal: build composite simulations via a simple web interface (years 2-3)."
</details>

---

## Aim 2. Composition Interface Protocol (CIP)

All three parts of the protocol exist as running code, described by an arXiv paper and per-repo design docs, but
there is no single versioned specification and nothing has gone to COMBINE. That gap is the most important Aim 2
item; see [D1](DEVIATIONS.md#d1).

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A2.1a | Process interface: typed ports, queryable for ports/types/parameters/initial state/update, RPC-capable | standard | Y1 | in-spirit | process-bigraph paper arXiv:2512.23754 · `process-bigraph` v1.8.4 `Process`/`Step` API · `bigraph-schema` 1.6.0 typed ports incl. unit dimensions · RPC forms: `rest-process` (`/list-types`, `/list-processes`, …), `python-process`, `docker-process`, `julia-process`, `cpp-process` | Write it down (D1); TR&D1 variable abstraction and TR&D2 annotations on ports not evidenced |
| A2.1b | Composite specification: wires from ports to shared states; adapters as processes | standard | Y1 | in-spirit | process-bigraph composite document (`processes`, `inputs`/`outputs` wires, `state`) · `process-bigraph-lang` DSL (Feb 2026) | Same |
| A2.1c | Orchestration methods: multi-timestep scheduler and DAG workflow of steps; event-driven restructuring | standard | Y1 | in-spirit | process-bigraph interval-based update scheduling and dependency-triggered `Step`s; runtime add/remove of processes `?` | Confirm event-driven restructuring |
| A2.2 | Exchange format (JSON/XML) for process interfaces and composites; integrated into community standards | standard | Y1, grows | in-spirit | JSON `.pbg` documents; `.pbif` (`bsander`); OMEX packaging in `pbest`; `bscose`/`sed` for SED2 | COMBINE engagement not evidenced (see A4.3) |
| A2.spec | *Implied:* a versioned, human-readable CIP specification | standard | Y1 | in-progress | arXiv:2512.23754 · `process-bigraph/docs/architecture.md`, `docs/concepts/composites-and-templates.md`, `docs/distributed_lifecycles.md` · `bigraph-schema/doc/method_api_spec.md`, `doc/composite_algebra.md`, `doc/address_portability_and_discovery.md` · `vivarium-guide` | Consolidate into one versioned `CIP-spec`; this closes A2.1a–c and A2.2 |

<details><summary>Grant wording</summary>

"This requires three things – (1) composition interface protocol - a standardized interface for sub-models, (2)
Composition exchange format - a composite specification 'wiring diagram' that declares how the sub-models connect, and
(3) execution methods for orchestrating the co-simulation." Process interface: "ports that specify data types, using
an abstraction of variables developed with TR&D1 and a formal ontology developed with TR&D2 that will include
annotations such as units, semantics, and provenance. It will support distributed, network-based communication using
a remote procedure call." Milestones: "(1) Composition interface protocol (CIP) […] (year 1). (2) CIP exchange format:
XML and JSON-based formats for declaring a composite simulator with the CIP (year 1)."
</details>

---

## Aim 3. composeBiosimulations: tools that implement the CIP

### Task 3.1 Process interfaces for Biosimulators

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A3.1 | Each Biosimulator exposes a process interface; cycle-1 tools auto-wrapped via `biosimulators_utils` | infra | Y1–2 | in-spirit | hand-written wrappers instead of auto-wrapping: `biosimulator-processes` 0.3.12 (COPASI, COBRA, tellurium, …) · `bspil-basico` · `viva-copasi` · `viva-tellurium` · `viva-amici` · `viva-pysces` · `viva-opencor` · `viva-smoldyn` · `viva-nfsim` · `pbsim_common` · `biosimulations/registry` | Count wrapped vs. the 15+ cycle-1 Biosimulators; see D3 |

### Task 3.2 Orchestration engine

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A3.2 | Vivarium 2.0 ingests the exchange format and returns an executable composite; multi-timestep + workflow orchestration | infra | Y1 | delivered | `process-bigraph` v1.8.4 (Sep 2026) · `pbest run file.pbg` · `vivarium-interface` | — |
| A3.2.hosted | "Integrated with runBioSimulations as its underlying orchestration engine, to support running composite simulations online" | infra | Y1 | deviated | online execution exists via this repo (`compose.cam.uchc.edu`, SLURM) and `viva-api` (`sms.cam.uchc.edu`), not via runBioSimulations | See [D2](DEVIATIONS.md#d2) |
| A3.2.engines | "Work with collaborators to build additional execution engines that support the standard" | collab | Y1+ | not-started | no second orchestrator exists: `viva-compiler`, `SimpleProcessBigraphRuntime`, `pbest` and `bsew` all delegate to `process_bigraph.Composite`; the `*-process` repos are single-process language bridges, not orchestrators | Name a collaborator engine or record as descoped in DEVIATIONS |

### Task 3.3 Methods for composite specification

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A3.3a | Static composite checker with suggestions | infra | Y1 | in-progress | `bigraph-schema` validation · `process-bigraph-lang` LSP diagnostics · `bsander` (resolves abstract/missing components) · `viva-template` `lint-workspace.py` | No single checker that reads a composite and returns suggestions; decide whether the LSP is it |
| A3.3b | Python scripting API for building, inspecting, running, evaluating composites; export to exchange format | infra | Y2–3 | delivered | `vivarium-interface` (Jun 2026) · `pbest` `CompositeBuilder` incl. parameter scans · `viva-superpowers` / `pbg-superpowers` | — |
| A3.3c | In-line visualization of composites | infra | Y2 | delivered | `bigraph-viz` (Jul 2026) · bigraph-loom renderer (`vivarium-guide`) · workbench composite views | — |
| A3.3d | Annotation-based semi-automated composition (units, UniProt, adapter insertion) with TR&D2 | infra + collab (TR&D2) | unspecified | in-progress | unit-dimension types in `bigraph-schema` (visible in `rest-process /list-types`) · `viva-compiler` | Ontology/UniProt matching not evidenced; needs TR&D2 input |
| A3.3e | Adapter registry: registry of type/unit converters; checker suggests adapters | infra + standard | begin Y1 | in-progress | adapters exist but are not a registry category: `viva-simularium` (generic output adapters) · `viva-basic-processes` (MathExpression, Clock, Intervention) · registries: `viva-catalog` ecosystem index, `biosimulations/registry` | Add an `adapter` tag/category to `viva-catalog` and seed counts↔concentrations, current↔molar flow |

### Task 3.4 Methods for composite deployment

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A3.4.pypi | Biosimulators released as PyPI packages usable from notebooks | infra | unspecified | delivered | `process-bigraph`, `bigraph-schema`, `vivarium-interface`, `pbest`, `biosimulator-processes`, and the `viva-*` family on PyPI; `ecoli-notebooks` | — |
| A3.4.docker | Docker API for composition: each simulator in its own container exposing the Process Interface with repeated-call comms | infra | unspecified | in-progress | `docker-process` runs **one** containerized process from a host orchestrator (`test_docker_process`), no CI · repeated-call protocol is CI-verified only over REST (`rest-process` `test_rest_protocol_drives_grow_process`) · `pbest containerize` and `bsew` put the **whole** composite in one container · upstream `process_bigraph/protocols/` has ray/rest/pool/session, no docker | Build one composite with processes in separate containers |
| A3.4.oci | *(not a grant commitment; recorded here because it bears on A3.4.docker)* Explore OCI-native container runtimes on HPC, rootless for trusted images and microVM-isolated for untrusted ones | infra | — | not-started | direction set 2026-09-11; see [plan-container-runtimes.md](../../../plan-container-runtimes.md) | Ask the cluster administrators what runtimes they support |
| A3.4.mixed | Mixed local / cloud / HPC processes in one composite | infra | unspecified | in-progress | `process_bigraph/protocols/` ships `ray.py`, `pool.py`, `session.py`, `clusters/ec2_ssm.py` with `docs/distributed_lifecycles.md` · local (`pbest run`) + HPC (this repo) + cloud (`viva-api`, `sms-cdk`) exist as separate paths | Demonstrate one composite spanning two backends |
| A3.x.steer | Semi-automation: simulation steering module | exploratory | — | in-progress? | `viva-basic-processes` Intervention process | Optional |

<details><summary>Grant wording (milestones)</summary>

"(1) Orchestration Engine: Vivarium will be updated to read the CIP exchange format (year 1). (2) Static composite
checker: will read the composition specification and provide guidance (year 1). (3) Python scripting API: import
individual Biosimulators as Python modules (year 2-3). (4) In-line visualization: a graphic depiction of a composite,
showing processes, states, and wires (year 2). (5) Adapter registry: will include methods for converting between data
types (begin year 1, and gradually add more adapters)."
</details>

---

## Aim 4. Composite Biosimulators: templates

### Task 4.1 Hybrid templates (Table 1)

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A4.1.ode-ssa | ODE/SSA hybrid (high-count species deterministic, low-count stochastic) | infra + science | **Y2** | not-started | `bio-bundles` has Vilar ODE/SSA *fixtures* only; no composite found | Build from `viva-tellurium` + `viva-copasi` SSA + a counts↔concentrations adapter (also seeds A3.3e) |
| A4.1.ode-fba | ODE/FBA (fluxes constrain FBA) | infra + science | **Y2** | delivered | `spatio-flux` (spatial dFBA) · `cdFBA` · `CRM-FBA` · `viva-comets` · `bio-bundles/dfba` | Publish one as the canonical template in `viva-template` |
| A4.1.fba-bool | FBA/Boolean (Boolean network gates FBA reactions) | infra + science | **Y2** | not-started | none | Needs a Boolean process (BoolNet/GINsim were cycle-1 Biosimulators) |
| A4.1.particle-pde | Particle-based/PDE (Smoldyn + VCell PDE coupling) | infra + science | Y1–5 | in-progress | `viva-smoldyn` and `viva-vcell-fvsolver` exist separately; `viva-membrane-actin-composite` couples particles to mechanics | Compose the two; reproduce ref [4] |
| A4.1.ode-pde | ODE/PDE region variables on membranes/volumes | infra + science | Y1–5 | in-progress | `viva-fenics` couples a reaction process to real dolfinx PDEs via shared stores in `composites/reaction_diffusion.py` (Fisher–KPP) and `composites/turing_patterns.py`, both unit-tested; its studies are still `planned`. The reaction side is hand-written, not a wrapped ODE simulator | Wire `viva-tellurium`/`viva-copasi` to fenics or fvsolver; no simulator-to-simulator ODE/PDE composite exists |
| A4.1.rbm-ode | RBM/ODE (NFSim observables feed ODEs) | infra + science | Y1–5 | in-progress | `viva-nfsim` (Jul 2026) · `viva-composite-nfsim-caspule` couples NFSim to MD instead of ODE | Add the ODE pairing |
| A4.1.compartment | Compartment models with permeability, volume/shape, motility (with CP6) | science + collab (CP6) | Y1–5 | in-progress | `viva-autopoiesis` covers all three properties at toy fidelity: `processes_spatial.py::SpatialContainment` (permeability-gated transport), `Boundary` (volume derived from membrane lipids), `Chemotaxis` (motility); five completed studies including adversarial probes | CP6 involvement: none found, this is solo work. Raise fidelity beyond the self-described "toy metabolism" |

### Task 4.2 Multi-cell templates (Table 2)

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A4.2 | ABM templates with intracellular (FBA/logical, ODE/RBM, FBA/ODE/RBM) and environment (compartment/ODE, lattice, PDE, CPM) algorithms; reproduce Table 2 models | science + collab | later years | in-progress | `viva-tumor-tcell` (Sep 2026; Table-2-class ABM) · environments `viva-cpm`, `viva-artistoo`, `viva-compucell3d`, `viva-chaste`, `viva-yalla`, `vivatyssue`, `vivarium-multibody` · `v2ecoli` colony work · `viva-biofilm`, `pbg-eps-biofilm` · `multiscale-bioprocess` | Pick one Table 2 paper (refs 27–33) and reproduce it as the first named template |
| A4.2.external | Invite external multi-algorithm solvers as Biosimulators; cross-validate against composites | collab | later years | in-progress | `viva-compucell3d`, `viva-chaste` wrap whole platforms; `biomodels-comparison` is the cross-validation pattern | Run one side-by-side comparison |

### Task 4.3 Community coordination

| Id | Commitment | Kind | Promised | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| A4.3.imag | Present at IMAG | community | ongoing | ? | not assessable from code | User to fill |
| A4.3.combine | COMBINE subgroup on multi-cell/multi-scale; HARMONY hackathons with Morpheus/CC3D/PhysiCell | community | ongoing | ? | `hra-hackathon` (Mar 2026) is the only hackathon repo; `vivarium-guide`, `meta-modelers-guide` are outreach artifacts | User to fill; this is also where A2.2's "integrate into community standards" lands |
| A4.3.syncell | Synthetic-cell modeling hackathon with CP6 and CP10 | community + collab | ongoing | not-started | no hackathon artifact in any of the three orgs | Confirm from non-GitHub records, or schedule |

<details><summary>Grant wording (milestones)</summary>

"(1) Multi-algorithmic and (2) multi-cell simulation templates. […] These will be worked on one at a time (year 1-5).
The initial hybrid simulation templates for ODE/SSA, ODE/FBA, and Boolean/FBA will be released in year 2. More complex
simulators will require more advanced tooling, which will only be available a few years in."
</details>

---

## Collaborative Project commitments

| Id | CP | We push | We pull | Status | Evidence | Next |
|---|---|---|---|---|---|---|
| CP1 | Cell Collective | protocol + annotation-based composition | gene regulation, signaling, metabolism, intercellular methods | ? | none found | User to fill |
| CP4 | Simularium | 3D outputs | Cytosim, MEDYAN, ReaDDy, cellPACK | in-progress | push: `viva-simularium`, `Biosimulators_simularium` (2024) · pull: MEDYAN ✓ ReaDDy ✓ cellPACK ~ Cytosim ✗ | Close Cytosim decision (A1.2.cytosim) |
| CP6 | Synthetic Cells & Organelles | protocol | compartment-model specification | not-started | code/issue/PR search across the three orgs for CP6, synthetic cell, protocell, vesicle, JCVI, syn3A finds nothing; `viva-autopoiesis` is in-spirit but names no external collaborator | Confirm from non-GitHub records (email, subaward, progress report); GitHub cannot rule out an unrecorded collaboration |
| CP7 | SASCO (stress-adapted cancer organelles) | protocol for reaction-diffusion + regulation | condensate reaction methods | ? | none found | User to fill |
| CP9 | Digital twins for synthetic biology | protocol + ensemble/inference processes | inference process interface | in-progress | `viva-uq` · `viva-torch` surrogates · `viva-ketchup` parameter estimation · `FBAKineticsPrototype` · `pbest` parameter scans | Name the "ensemble of simulations" process |
| CP10 | Cell-free expression / NIST | interface, tools, models | experimental protocols | ? | none found | User to fill |

---

## How to maintain this file

- One row per commitment; never merge rows, split them when a row starts needing two statuses.
- Change a status only with an evidence link, or with a DEVIATIONS entry for `in-spirit`/`deviated`/`dropped`.
- Remove a `?` when a person has confirmed the row. Update the roll-up counts and the date when you do.
- Keep grant wording in the `<details>` blocks verbatim; paraphrase only in the `Commitment` column.
