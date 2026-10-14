# Environments research (epoch 2)

**Status (2026-10-13):** research complete. The decisions it supports are in
[plan-environments-epoch2.md](../plan-environments-epoch2.md), all proposed.

The questions:
- How do we find a **forest of compatible environments** for the steps, processes, composites and OS dependencies we
  run, given that the same item belongs in many of them?
- How do we **run a composite whose items cannot share one environment**: across processes, containers and machines,
  on HPC and on Linux, macOS and Windows laptops?
- How are those environments **versioned and registered**?

Epoch 1 ([plan-environment-builds.md](../plan-environment-builds.md)) made builds jobs with recorded artifacts. This
research is the basis for epoch 2.

## Reading order

| Chapter | What it answers |
|---|---|
| [01 — Environments today](01-current-state.md) | What compose-api, pbest, process-bigraph, the workbench and the viva catalogue do now, with file:line citations |
| [02 — Packaging and isolation](02-packaging-and-isolation.md) | pixi (as a conda + CPython build system), uv, conda, Spack, Nix/Guix, OCI and Apptainer, plus prior art from workflow systems |
| [03 — The forest](03-forest-algorithms.md) | The overlapping-cover problem, algorithms to compute it, sharing the overlap, version skew, shared middleware in the catalogue |
| [04 — Coupling and execution](04-coupling-and-execution.md) | Topologies, MUSCLE3 and other coupling frameworks, IPC and wire formats, task frameworks, placement, data cost |
| [05 — Platforms](05-platforms.md) | HPC, Linux, macOS and Windows, native and in containers |
| [06 — Research islands](06-research-islands.md) | Multicellular modelling (CPM, vertex, agent-based) and other islands with their own interoperability needs |
| [References](references.md) | Every external source, by chapter |

Each chapter ends with **Constraints** (facts the design must respect) and **Unknowns** (what an experiment or a
question must settle). A claim we could not check against a source is marked *(unverified)*.

## Glossary

| Term | Meaning |
|---|---|
| **item** | A unit someone wants to run: a package, a step, a process, a composite, or an OS dependency (a solver library, a runtime) |
| **island** | The research name for an **environment** in the forest; code, API and UI keep the word *environment* ([EV0](../plan-environments-epoch2.md)). A locked, identified environment: a set of items at resolved versions, for one or more platforms. Today's `registry_env` and `viva-pde-particle` images are islands |
| **forest** | The set of islands we maintain |
| **cover** | The forest seen as sets of items. Islands **overlap**: common middleware (adapters, solvers, IO, viz, data processing, the process-bigraph core) sits on many islands. It is a cover, not a partition |
| **core** | The common middleware feature every island carries, ideally at identical versions (one solve-group) |
| **skew** | One item at different versions on different islands |
| **feasibility oracle** | The resolver deciding whether a set of items co-installs (a lock succeeds or explains a conflict) |
| **placement** | The assignment of a composite's nodes to islands |
| **cut wire** | A wire between nodes placed on different islands; its state crosses a process boundary |
| **worker** | A long-lived process in one island that hosts the composite's nodes placed there and talks to the coordinator |
| **launcher** | The command that starts a worker on a platform: `python`, `pixi run`, `docker run -i`, `apptainer exec`, `srun` |
| **sidecar island** | An island whose items are not Python (Node, Java, C++ binaries), wrapped by a worker that speaks the same protocol |
| **lock hash / digest** | An island's identity before and after an image exists (EV1) |
