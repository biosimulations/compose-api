# TR&D3 deviations log

Append-only record of decisions to deliver a grant commitment in a different form, replace it, descope it, or drop
it. Every `in-spirit`, `deviated`, or `dropped` row in [TRACKER.md](TRACKER.md) must point at an entry here. The
grant's own "Pitfalls and Alternatives" paragraphs pre-authorize several of these rationales; cite them when they
apply.

A new entry may be drafted from repository evidence and marked **PROPOSED** in its heading; it is not in force until
a person reviews it and fills in `Agreed by`. Do not leave an entry marked PROPOSED once reviewed. D1–D3 below were
accepted on 2026-09-09.

## Entry template

```
## Dn. <short title>
- Date: YYYY-MM-DD
- Commitments: <TRACKER ids>
- Grant said: <one or two sentences, quoting where useful>
- We are doing: <what exists or is planned instead>
- Why: <reason; cite the grant's pitfalls paragraph if it applies>
- Still owed: <what would make this "delivered" rather than "in-spirit", or "nothing">
- Agreed by: <names>
```

---

## D1. The Composition Interface Protocol exists as code, not as a written specification
- Date: 2026-09-09
- Commitments: A2.1a, A2.1b, A2.1c, A2.2, A2.spec
- Grant said: Aim 2 delivers "a standardized interface for sub-models", "a composite specification 'wiring diagram'",
  "execution methods", and "XML and JSON-based formats for declaring a composite simulator", all in Year 1, and will
  "integrate it into community standards".
- We are doing: the protocol is fully realized by `bigraph-schema` (typed ports with unit dimensions, serializable
  schemas), `process-bigraph` (Process/Step interface, composite documents, multi-timestep and step-DAG
  orchestration), and the RPC bridges (`rest-process`, `python-process`, `docker-process`, `julia-process`,
  `cpp-process`). The exchange format is the JSON `.pbg` document. The protocol is described in the process-bigraph
  paper (arXiv:2512.23754), in `process-bigraph/docs/` (architecture, composites-and-templates, distributed
  lifecycles) and `bigraph-schema/doc/` (method API spec, composite algebra, address portability), and in the
  interactive `vivarium-guide`. There is no single versioned specification and nothing has been submitted to COMBINE.
- Why: the code moved faster than a written standard could, and the ecosystem (dozens of `viva-*` wrappers) validated
  the interface in practice before it was frozen. That is a defensible order of operations, but a standard that only
  exists as one implementation is not yet a community standard.
- Still owed: a `CIP-spec` document (versioned, derived from the code: type system, process interface contract,
  composite document schema, orchestration semantics) and one COMBINE/HARMONY presentation of it. With those, the
  five rows above become `delivered`.
- Agreed by: Jim Schaff, 2026-09-09

## D2. Online composite execution runs on compose-api and viva-api, not inside runBioSimulations
- Date: 2026-09-09
- Commitments: A3.2.hosted, A1.4
- Grant said: "Vivarium 2.0 will be integrated with runBioSimulations as its underlying orchestration engine, to
  support running composite simulations online", and Aim 1.4 promised a composition web page inside BioSimulations 2.0
  with results "saved in the same BioSimulation repository that currently holds simulations of single simulators".
- We are doing: composites run remotely through `biosimulations/compose-api` (SLURM/HPC at compose.cam.uchc.edu,
  driven by `pbest`) and through `vivarium-collective/viva-api` (sms.cam.uchc.edu) behind `vivarium-workbench`, which
  is the composition UI. `biosimulations/platform` is being built as the BioSimulations 2.0 backend/frontend (BSVS)
  but does not yet host composition or composite results.
- Why: the cycle-1 runBioSimulations stack (Angular/Nest monorepo, SED-ML/OMEX job model) was a poor fit for
  iterative co-simulation; the grant's own Aim 2 pitfalls note that co-simulation "lies somewhere in between" MPI-style
  and cloud-microservice coupling and needs a different execution model. Standing up dedicated services was the
  faster route and preserved the HPC path.
- Still owed: either (a) expose composite runs and results through `biosimulations/platform` so they sit next to
  single-simulator studies, or (b) formally declare the workbench + compose-api/viva-api pair as "BioSimulations 2.0
  composition" and cross-link from biosimulations.org. Either closes A1.4 and A3.2.hosted.
- Agreed by: Jim Schaff, 2026-09-09

## D3. New simulators are wrapped as process-bigraph processes, not as BioSimulators-compliant containers
- Date: 2026-09-09
- Commitments: A1.2.*, A3.1, A1.4.onboard
- Grant said: Task 1.2 would "containerize and validate more simulators" into the BioSimulators registry, and Task 3.1
  would give cycle-1 Biosimulators a process interface "automatically […] by leveraging the shared API developed in
  biosimulator_utils".
- We are doing: each new simulator gets a `viva-*` repository implementing the process-bigraph `Process` interface
  directly (ReaDDy, Mem3DG, MEDYAN, cellPACK, CPM via three routes, Smoldyn, NFSim, CompuCell3D, Chaste, and more),
  discoverable through `viva-catalog` and `biosimulations/registry`; cycle-1 tools were re-wrapped by hand in
  `biosimulator-processes` and `bspil-basico` rather than auto-derived from `biosimulators_utils`. Containerization
  happens per composite via `pbest containerize` and `bsew`, not per simulator via the BioSimulators CLI convention.
- Why: the process interface is what Aims 3 and 4 consume; a SED-ML command-line container adds a layer that
  co-simulation cannot use for repeated small updates (the Aim 3 pitfalls paragraph anticipates exactly this:
  "many simulators were not designed to be called repeatedly in quick succession"). Auto-wrapping proved less useful
  than hand-written wrappers because port types have to be chosen per simulator.
- Still owed: nothing for the interface itself. For the registry promise, make sure every `viva-*` simulator is listed
  in `viva-catalog` and, where a cycle-1 BioSimulators entry exists, cross-referenced from it. Cytosim remains
  genuinely not started and needs its own decision (drop, or substitute with MEDYAN + ReaDDy). A Cahn-Hilliard
  composite does exist in `meta-modelers-guide` (found in the 2026-09-09 verification pass), so that one needs
  promoting to a named artifact rather than starting from scratch. Two wrappers that exist are not yet trustworthy:
  `viva-mem3dg` has no validation case and no CI, and `viva-compucell3d` has smoke tests only.
- Agreed by: Jim Schaff, 2026-09-09
