# Research islands beyond ours

**Status (2026-10-13): research, not a plan.** This chapter looks at the multicellular modelling tools a composite
might want to couple to, and at what each would need to run beside process-bigraph. It covers the standards that
exist, the coupling precedents, and what follows for our port types and workers. It then maps the islands already in
our own catalogue onto four isolation classes.

Sources are web research done on 2026-10-13 and a read of the viva-* catalogue on the same day. Claims that come from
memory or inference rather than a fetched source are marked *(unverified)*. CompuCell3D's packaging was re-checked
while this chapter was written. It is marked **(verified 2026-10-13)**, and one claim in the source report was dropped
as a result (see "Spot-check" at the end).

## Isolation classes used here

| Class | What it is | How a worker starts | Examples |
|---|---|---|---|
| **native island** | a Python environment from PyPI wheels, resolved by uv | `python -m …` in a venv, or an image built from the lock | COPASI, tellurium, tyssue |
| **conda island** | a conda-forge (+PyPI) environment, locked by pixi | `pixi run …`, or an image built from `pixi install --locked` | FEniCS/dolfinx, CompuCell3D, PyChaste |
| **sidecar island** | a non-Python runtime (Node, JVM, a Docker image) driven by a thin Python wrapper | the wrapper launches the runtime as a child process or a container | Artistoo, Chaste, tstmd, comets |
| **prebuilt image** | an image its owner builds and publishes, pinned by digest; the service never builds it | `apptainer exec <sif> …` (as `viva-pde-particle` is today) | anything compiled per model, GPU codes, the not-installable |

Two notes on these classes:
- A native or conda island can also be shipped as an image. The class records what is needed to **reproduce** the
  environment, not how it travels.
- On the HPC side a sidecar island that needs Docker has to become a prebuilt Apptainer image, because the SLURM nodes
  run Apptainer.

## 1. Multicellular modelling ecosystems

| Tool | Method | Core | Packaging (as of 2026-10-13) | Coupling hooks | Isolation driver | Class |
|---|---|---|---|---|---|---|
| **CompuCell3D** | Cellular Potts (CPM) | C++ with Python steppables | conda: `conda install -c compucell3d -c conda-forge cc3d` **(verified 2026-10-13, [repo](https://github.com/CompuCell3D/CompuCell3D))**; binary distributions from the project page; runs on Windows, Mac and Linux; the source build pulls `tbb_full_dev` from the `compucell3d` channel and installs libroadrunner and antimony with pip ([build](https://compucell3d.org/SrcBin/CC3D_4xx_linux_compile_conda_based)) | per-cell libRoadRunner for SBML ([libRR](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9825722/)) | conda-only; a project channel on top of conda-forge | conda island |
| **Morpheus** | CPM and PDE | C++, models in MorpheusML (XML) | binaries | SBML imported by conversion to MorpheusML ([FitMulticell](https://fitmulticell.readthedocs.io/en/stable/example/SBML_example.html)) | not Python, XML-driven | sidecar or prebuilt image |
| **Artistoo** | CPM | JavaScript | runs in the browser ([eLife](https://elifesciences.org/articles/61288)) | none | needs a JS runtime | sidecar island (Node) |
| **PhysiCell / PhysiBoSS** | agent-based, centre-based | C++ with OpenMP | source build; on macOS it needs `PHYSICELL_CPP` pointing at an OpenMP-capable g++ ([releases](https://github.com/MathCancer/PhysiCell/releases)) | MaBoSS Boolean networks (PhysiBoSS); SBML ODEs through libRoadRunner, with fixes in 1.13 | OpenMP; **compiled per model** | prebuilt image, or a compile step in the worker |
| **Chaste / PyChaste** | vertex and other cell-based models | C++ | `mamba -c pychaste -c conda-forge` ([PyChaste](https://github.com/Chaste/PyChaste)) | CellML code generation | conda-only; the Python API covers part of Chaste | conda island (PyChaste) or prebuilt image |
| **tyssue** | vertex models | Python, pandas | pip ([docs](https://tyssue.readthedocs.io/)) | — | light | native island |
| **cellGPU** | vertex and Voronoi models | CUDA C++ | source build ([paper](https://arxiv.org/pdf/1702.02939)) | — | GPU | prebuilt image (CUDA) |
| **Tissue Forge** | particle-based | C++/CUDA with Python | conda | — | one GPU; windowless mode advised for headless runs ([GPU](https://tissue-forge-documentation.readthedocs.io/en/stable/cuda.html)) | conda island, on a GPU node |

The "Class" column is our inference from the packaging, not something the projects state. The "Method" entries for
PhysiCell, cellGPU and Tissue Forge are general knowledge *(unverified)*. As of 2026-10-13,
vivarium-collective has **no PhysiCell or MUSCLE3 wrapper**. CompuCell3D, Artistoo, Chaste and tyssue appear in the
catalogue (section 5).

## 2. Standards

| Standard | Year | Scope |
|---|---|---|
| [MultiCellDS](https://www.biorxiv.org/content/10.1101/090696.full.pdf) | 2016 | digital cell lines and simulation snapshots: data, not coupling |
| [MultiCellML](https://tu-dresden.de/zih/forschung/projekte/multicellml) | BMBF project, 2018–19 | exchange of model descriptions across simulators |
| [COMBINE workshop on multicellular modelling](https://fairdomhub.org/events/194) | 2019 | cross-simulator exchange |
| [Standardizing Multicellular Simulation](https://systemsmedicine.pulmonary.medicine.ufl.edu/wordpress/files/2023/10/Standardizing-Multicellular-Simulation.pdf) (Agmon, Sego, Glazier) | 2023 | continues the description and exchange work |
| [OpenVT](https://cms.unl.edu/ianr/biochemistry/global-alliance-for-immune-prediction-and-intervention/news/viral-pandemics-wg-seminar-series-may-2-2024-slides-and-youtube-available) | seminar 2024-05-02 | CompuCell3D and PhysiCell communities, continuing the 2023 work |

**There is no runtime-exchange standard.** As of 2026-10-13, the research found none for exchanging state between
running multicellular simulators. The standards cover model descriptions and snapshots. A process-bigraph coupling
would define its own port types (section 4), and MultiCellDS is the nearest vocabulary for a cell-population snapshot
*(unverified as a fit)*.

## 3. Coupling precedents

All three precedents embed an SBML engine **inside** the multicellular code. None couples two independent simulators
across a process boundary.

| Precedent | How | What it shows |
|---|---|---|
| **PhysiCell + libRoadRunner** | each agent carries an SBML ODE model solved by libRoadRunner; fixes landed in PhysiCell 1.13 ([releases](https://github.com/MathCancer/PhysiCell/releases)) | intracellular ODEs per agent, in-process, sharing PhysiCell's OpenMP threads |
| **CompuCell3D + SBML** | per-cell libRoadRunner instances from Python steppables ([libRR paper](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9825722/)) | the same pattern in a CPM code; libroadrunner comes from pip into a conda environment in the source build |
| **Morpheus + SBML** | SBML is converted to MorpheusML and becomes part of the model ([FitMulticell example](https://fitmulticell.readthedocs.io/en/stable/example/SBML_example.html)) | coupling by translation, before the run, not at run time |

Implications for us:
- The established pattern is in-process: the multicellular code owns the cells and calls a small solver per cell.
- If process-bigraph puts the SBML model in another island, each tick crosses a boundary once **per cell**. Batching
  per tick (the `ray:` protocol's `batch_update`, chapter 04 section 6) is then mandatory, not an optimisation.
- Mixing pip libroadrunner into a conda environment, as CompuCell3D's source build does, is the duplicate-native-
  library hazard noted for pixi: a wheel bundles its own libraries next to conda's *(unverified for libroadrunner
  specifically)*.

## 4. Implications for port types and workers

These are our inferences from the table above.

### 4.1 Lattice ↔ continuum/agent mapping as explicit adapter items

- A CPM (CompuCell3D, Morpheus, Artistoo, viva-cpm) represents a cell as a set of lattice sites. An agent or vertex code
  (PhysiCell, tyssue, Chaste) represents it as a point, polygon or polyhedron. A PDE code represents it as a field
  over a mesh.
- Crossing between them needs a mapping:
  - voxel set ↔ centroid and volume;
  - lattice cell id ↔ agent id;
  - lattice field ↔ mesh field (interpolation).
- That mapping should be an **adapter item** with its own ports, not hidden inside a transport. Then it can be placed
  (by producer fusion, chapter 04 section 7.2: on the side that shrinks the data), tested, and versioned.

### 4.2 Variable-length port types

- Agent populations change size: cells divide, die and migrate.
- A fixed-shape grid port (MUSCLE3's `Grid`, a numpy array of fixed shape) does not describe them.
- Ports need **ragged or table types**: an Arrow record batch with one row per cell and columns for id, position,
  volume and type. Arrow IPC carries this across islands with a stable format (chapter 04 section 4.2).
- MUSCLE3's resizable vector ports are the coupling-framework precedent for a variable number of peers.

### 4.3 One long-lived worker per OpenMP or GPU code

- PhysiCell (OpenMP), cellGPU (CUDA) and Tissue Forge (one GPU) parallelise internally.
- Each wants **one long-lived worker** that owns many cores or one GPU, sized through `OMP_NUM_THREADS` or the GPU
  assignment. They never want one worker per cell, and they should not be restarted per step.
- In SLURM terms the worker's job step requests its cores or GPU. A pilot (chapter 04 section 5.5) can place it within
  the allocation.

### 4.4 Compile-per-model codes

- PhysiCell compiles a model into its executable. AMICI (section 5) compiles a C++ module per SBML model.
- The image is then the environment **plus** the model, or the worker needs a compiler at run time and a cache of
  compiled models.
- Either way, the identity of what ran includes the compiled model, not just the environment's digest.

### 4.5 Conda-only stacks

- CompuCell3D (a project channel on conda-forge), PyChaste (a `pychaste` channel), Tissue Forge, and FEniCS/dolfinx all
  install through conda.
- pip-only resolution cannot cover them. Islands holding them are conda islands (pixi), and extra channels are part of
  their identity.

## 5. Our own adjacent islands

From the viva-* catalogue survey of 2026-10-13 (`viva_catalog/modules.json`, 48 entries, and the pyprojects of about 50
repos). The catalogue records no Python version, packaging, engine or native dependencies, so this classification was
read from each repo's manifests.

| Family | Wrappers | Packaging | Python floor | Class |
|---|---|---|---|---|
| Pure pip wheels | COPASI, tellurium, readdy, smoldyn, LAMMPS, opencor, nfsim/bionetgen, pysces, torch, pennylane | PyPI wheels | >=3.11 | native island |
| Needs conda-forge | fenics/dolfinx (pixi), compucell3d `cc3d` (pixi, osx-arm64 only), ketchup (ipopt/pyomo) | conda-forge | varies | conda island |
| Rust / maturin | viva-cpm, viva-biofilm | maturin builds | >=3.12 | native island once wheels exist; else built |
| External runtimes | Artistoo (Node), Chaste and tstmd (Docker), comets (Java) | a wrapper plus another runtime | varies | sidecar island |
| Compiler at run time | AMICI (a C++ compiler per model) | PyPI plus a toolchain | >=3.12 | native island with a compiler, or prebuilt image |
| Not installable | oxidizeme (Python 2.7, proprietary qMINOS) | — | — | none, at best an owner-supplied image |

### 5.1 PDE and particle: viva-pde-particle (FEniCS, Smoldyn)

- As of 2026-10-13 it is the only locked, SHA-pinned environment in the org, and one of the two deployed environments
  (kind `prebuilt`, pinned by digest).
- Its `pixi.toml` uses conda-forge for `osx-arm64` and `linux-64`, with `python 3.12.*` and `fenics-dolfinx 0.10.*` to
  match vcell-fenics.
- Smoldyn is built from a submodule, because there is no usable wheel. process-bigraph is pinned to a revision.
- Its `compose` environment shares a solve group with `default`, so the compose-api image (`docker/compose.Dockerfile`)
  has exactly `default`'s versions without the workbench.
- It runs process-bigraph 1.8.5 and bigraph-schema 1.7.0, while `registry_env` runs 1.0.5 and 1.0.14.
- **Isolation: a conda island, shipped as a prebuilt image.** It is the working precedent for that class. Its results
  are zarr stores, which suit exchange at checkpoint or analysis rate, not per tick.

### 5.2 Rust/maturin CPM: viva-cpm

- viva-cpm (and viva-biofilm) are Rust extensions built with maturin, with a floor of Python >=3.12.
- With published wheels for each platform, it is a **native island** member like any other wheel.
- Without them, every island that holds it needs a Rust toolchain at build time. pixi-build's Rust backend could make
  it a conda package, but pixi-build is a preview feature as of 2026-10-13.
- As a CPM, it is a lattice code: coupling it to an agent or PDE code needs the adapter of 4.1.

### 5.3 Node, Docker and Java sidecars: Artistoo, Chaste, tstmd, comets

- **Artistoo** needs a Node runtime. The wrapper drives it as a child process.
- **Chaste and tstmd** wrappers drive a Docker image. On a laptop that needs Docker Desktop. On SLURM, which runs
  Apptainer, the image has to be converted and run as a prebuilt image, and the wrapper's Docker calls replaced.
- **comets** needs a JVM.
- **Isolation: sidecar islands.** Each carries a Python wrapper (which can live in any native island) plus an external
  runtime. The bridge between them is per wrapper today: Docker or subprocess calls, with no shared protocol.
- A stdio worker protocol (chapter 04, architecture A) would let a sidecar answer the coordinator directly, with no
  Python wrapper in the middle, if the sidecar implemented the verbs *(inference)*.

### 5.4 Compile-at-runtime AMICI

- AMICI compiles a C++ module for each SBML model, so the island needs a C++ compiler at run time, and Python >=3.12.
- Options:
  - a native island that also carries a compiler (from conda's compilers, or the image's toolchain), plus a cache of
    compiled models on the shared store;
  - a prebuilt image per model, compiled ahead of time.
- Either way, the compiled model is part of what ran (4.4).

### 5.5 The not-installable oxidizeme

- It needs Python 2.7 and a proprietary solver (qMINOS). No resolver can produce it, and the service cannot
  redistribute it.
- **Isolation: none from us.** At most, an owner-supplied prebuilt image, run where its licence allows. It belongs
  outside any island the service builds.

### 5.6 Summary map

| Island | Class | Shipped as | Needs |
|---|---|---|---|
| pure-pip wrappers | native | the shared image (today `registry_env`), or a uv-locked image | a resolver solve per set |
| viva-pde-particle | conda | prebuilt image (pixi) | conda-forge, a source build of Smoldyn |
| compucell3d, ketchup | conda | image from a pixi lock | conda-forge (+ the `compucell3d` channel); `cc3d` osx-arm64 only in the wrapper's pixi.toml |
| viva-cpm, viva-biofilm | native | wheels, else built | Rust toolchain until wheels exist |
| Artistoo | sidecar | Node plus the wrapper | Node runtime |
| Chaste, tstmd | sidecar (laptop), prebuilt image (HPC) | Docker image, converted for Apptainer | Docker or Apptainer |
| comets | sidecar | JVM plus the wrapper | JVM |
| AMICI | native + compiler, or prebuilt image per model | image with a toolchain | C++ compiler, compiled-model cache |
| oxidizeme | none | owner-supplied image, if any | Python 2.7, proprietary qMINOS |

## Constraints

1. No runtime-exchange standard exists for multicellular simulators (2026-10-13). Port types for cell populations are
   ours to define.
2. The existing coupling precedents are all in-process SBML engines. Splitting the SBML side into another island costs
   one boundary crossing per cell per tick unless batched.
3. Several external codes are conda-only (CompuCell3D, PyChaste, Tissue Forge), compiled per model (PhysiCell), or
   GPU-bound (cellGPU, Tissue Forge). pip-only resolution covers none of them.
4. Docker-based sidecars do not run as-is on SLURM nodes, which run Apptainer.
5. Lattice codes (CPM) and agent, vertex or PDE codes do not share a representation of a cell. Every such coupling
   needs a mapping adapter.
6. viva-pde-particle and `registry_env` run different process-bigraph cores (1.8.5 vs 1.0.5), so any coupling between
   them crosses a core-version boundary as well (chapter 04 section 8).
7. oxidizeme cannot be built or redistributed by the service.

## Unknowns

- Whether CompuCell3D's `cc3d` is built for linux-64 and win-64 on its channel, beyond the wrapper's osx-arm64-only
  pixi.toml. The cluster needs linux-64.
- Whether PhysiCell can be driven step by step from outside (a stepping API), or only as a whole run per executable.
- Which multicellular code people actually want coupled first. That decides whether section 4's adapters and ragged
  ports are needed now.
- Whether MultiCellDS is a usable basis for a cell-population port schema.
- How the Chaste and tstmd Docker images behave under Apptainer conversion (users, writable paths, networking).
- Whether the GPU codes can be scheduled on our cluster at all: GPU partitions and drivers inside Apptainer (`--nv`)
  were not checked.
- Whether viva-cpm and viva-biofilm publish wheels for linux-64, and which Python versions those wheels cover.

## Spot-check (2026-10-13)

| Claim in the source report | Verdict |
|---|---|
| CompuCell3D installs from conda channels `conda-forge` + `compucell3d`, with libroadrunner from pip | **confirmed, refined**: the user install is `conda install -c compucell3d -c conda-forge cc3d` ([repo README](https://github.com/CompuCell3D/CompuCell3D)), with binary distributions on the project page for Windows, Mac and Linux. The pip installs of libroadrunner and antimony are in the **source-build** instructions, not the user install ([build](https://compucell3d.org/SrcBin/CC3D_4xx_linux_compile_conda_based)) |
| Installing other packages, for example PyTorch, into a CompuCell3D environment can break SBML | **dropped**: the cited page does not say this and does not mention PyTorch |

## Sources

- CompuCell3D: https://github.com/CompuCell3D/CompuCell3D, https://compucell3d.org/SrcBin/CC3D_4xx_linux_compile_conda_based
- libRoadRunner in multicellular codes: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9825722/
- Morpheus SBML import (FitMulticell): https://fitmulticell.readthedocs.io/en/stable/example/SBML_example.html
- Artistoo: https://elifesciences.org/articles/61288
- PhysiCell: https://github.com/MathCancer/PhysiCell/releases
- PyChaste: https://github.com/Chaste/PyChaste
- tyssue: https://tyssue.readthedocs.io/
- cellGPU: https://arxiv.org/pdf/1702.02939
- Tissue Forge: https://tissue-forge-documentation.readthedocs.io/en/stable/cuda.html
- MultiCellDS: https://www.biorxiv.org/content/10.1101/090696.full.pdf
- MultiCellML: https://tu-dresden.de/zih/forschung/projekte/multicellml
- COMBINE 2019 workshop: https://fairdomhub.org/events/194
- Standardizing Multicellular Simulation (2023):
  https://systemsmedicine.pulmonary.medicine.ufl.edu/wordpress/files/2023/10/Standardizing-Multicellular-Simulation.pdf
- OpenVT seminar: https://cms.unl.edu/ianr/biochemistry/global-alliance-for-immune-prediction-and-intervention/news/viral-pandemics-wg-seminar-series-may-2-2024-slides-and-youtube-available
- viva-* catalogue: `vivarium-collective/viva-catalog` (`viva_catalog/modules.json`), the wrappers' `pyproject.toml`
  files, and `viva-pde-particle/pixi.toml` (read 2026-10-13)
- compose-api: `compose_api/registry/environments.yaml`, `compose_api/registry/manifests/*.json`
- pixi-build: https://pixi.prefix.dev/latest/build/getting_started/
