# Environments, epoch 2: a forest of islands, and running across them

**Status (2026-10-13): proposed. No decision is taken yet.**
- This plan turns the research in [environments/](environments/README.md) into sixteen decisions (EV0–EV15); EV0 fixes the vocabulary, EV15 separates authoring. Each
  decision is gated by experiments (X1–X6) and staged in phases (E2.0–E2.4).
- Accepting a decision means editing its **Status** line, with a date and the PR.
- Epoch 1 is [plan-environment-builds.md](plan-environment-builds.md): phases 1–4 are shipped, and its phase 5
  (publish) is deferred to this plan's EV12.

## Why a second epoch

Epoch 1 made builds real jobs with recorded artifacts. It did not change *what* an environment is:
- Today's environments are one hand-curated bundle (`registry_env`) and one owner-published image
  (`viva-pde-particle`).
- The submitter picks between them.
- Identity is the md5 of a recipe that does not reproduce.
- Compatibility is decided by a person ([01 §1](environments/01-current-state.md)).

Three pressures make that untenable:
1. **The two islands already disagree on the core.** `registry_env` runs process-bigraph 1.0.5 and `viva-pde-particle`
   runs 1.8.5. Every current middleware package (emitters, basic processes, superpowers, workbench) needs ≥ 1.4.12,
   so none of it can join `registry_env` ([03 §shared middleware](environments/03-forest-algorithms.md)).
2. **The catalogue's items cannot share one environment.** It has 48 listed wrappers, and they span:
   - pure pip;
   - conda-only (FEniCSx, CompuCell3D);
   - Rust;
   - Node, Java and Docker sidecars;
   - compile-at-runtime (AMICI);
   - Python 2.

   Strategy rule 3 (split across containers) is not hypothetical
   ([01 §catalogue](environments/01-current-state.md), [06](environments/06-research-islands.md)).
3. **Users and collaborators run on four platforms.** HPC, Linux, macOS and Windows, each either in containers or
   native ([05](environments/05-platforms.md)).

**Vocabulary** (full glossary in [environments/README.md](environments/README.md)):
- An **item** is a package, step, process, composite or OS dependency.
- An **island** is a locked, identified environment.
- The **forest** is the set of islands. It is an **overlapping cover**: common middleware sits on many islands.
- A composite that spans islands has a **placement**. The wires it cuts are **cut wires**.

## Decisions

Each decision gives a recommendation, then the alternatives considered, the consequences, the evidence (chapter
links) and its status.

### EV0 — Reconcile the concepts: catalog, registry, environment, `registry_env`, simulator, bundle

The proof of concept grew its vocabulary one feature at a time. **The current implementations are not authoritative.**
This decision fixes the concepts first; EV1–EV14 are stated in its terms.

**What the words mean today** (2026-10-13; one word, many things):

| Word | Meanings in use today | Where |
|---|---|---|
| **registry** | (1) the *registry of record*: curated entries with `level`, `module_roots`, `bundles`, `evidence` | `compose_api/registry/manifest.yaml`, `manifest.py` |
| | (2) the shared image's *library list* (COPASI, Tellurium, ReaDDy, …), vendored from the `biosimulations/registry` repo's `registry.json` | `simulation/simulator_registry.json`, `simulator_registry.py` |
| | (3) the `/registry` API: environments, manifests, entries, solvers, images, builds | `api/routers/registry.py` |
| | (4) an OCI image registry (`ghcr.io/biosimulations/registry_env`) | `config.simulator_image_repository` |
| | (5) legacy "registered simulators/packages" | `/core` routes (`get-simulator-list`, …), tables `package`, `allow_list`, `simulator_to_package` |
| **catalog** | (1) `viva-catalog`: the external discovery index (`modules.json`, ecosystem index) | vivarium-collective |
| | (2) `catalog.yaml`: catalogue wrappers pinned at `listed`, generated from (1); `manifest.yaml` overrides it | `registry/catalog.py`, `catalog.yaml` |
| | (3) the web UI's **Catalog** page, which shows the merged registry entries | `webapp/app/pages/catalog.vue` → `/registry/entries` |
| | (4) the `/core` simulator, process and step lists | `api/routers/compute.py` |
| **environment** | (1) a named runtime with a kind (`shared` / `prebuilt`) and a Python entry command | `registry/environments.yaml`, `environments.py` |
| | (2) the run label `environment` | `simulation/labels.py` |
| | (3) the subject of builds and images | `/registry/environments/{name}/build`, `environment_image` |
| **`registry_env`** | (1) the shared environment's name | `environments.yaml` |
| | (2) the bundle constant every runnable entry must list | `SERVICE_BUNDLE`, `manifest.py` |
| | (3) the image repository name | `config.py` |
| | (4) a label value, and a solver's `environment` | `labels.py`, `solvers.yaml` |
| **simulator** | (1) an *environment version*: `Simulator` / `SimulatorVersion`, identified by `container_def_hash` | `simulation/models.py`, `simulator_tables.py` |
| | (2) a *prebuilt environment*: `?simulator=<name>`, `prebuilt_simulators` | `routers/simulation.py`, `config.py` |
| | (3) a simulation *engine library* (COPASI, Tellurium) | `simulator_registry.json` |
| | (4) a BioSimulators simulator (an image with a CLI) | BioSimulators conventions |
| **bundle** | (1) entry → environments it is installed in (`bundles:`) | `manifest.yaml` |
| | (2) a pre-built combination (strategy rule 2) | `strategy.md` |
| | (3) unrelated: the results bundle (`*.fenics`) | `observability/datasets.py` |

**Problems this causes:**
- An environment version is called a simulator.
- An environment is chosen through a parameter called `simulator`.
- "Registry" names both the curated record and a library list that bypasses it: the shared image installs
  `simulator_registry.json`, not the registry entries.
- `registry_env` hard-codes a single bundle into validation.
- The UI's "Catalog" is the registry, while the catalogue proper is external.

**Relation to [plan-sedml.md "Concepts"](plan-sedml.md#concepts-catalog-registry-environment-solver).** That
section already gave each word one job:
- *Catalog* meant the merged entries, as discovery and trust.
- *Registry of record* meant admission: the levels at `tested` and above.
- *Environment* and *solver* meant what they mean here.

EV0 refines it in three ways:
- Trust and admission are two thresholds on **one record**, so they merge into the **Registry**.
- *Catalog* is reserved for the external feeds.
- The library list that `plan-sedml.md` left as a follow-up ("generate `simulator_registry.json` and `manifest.yaml`
  from one list") is resolved by retiring the list.

**Proposed model.** Six concepts, each with one name:

| Concept | What it is | Replaces |
|---|---|---|
| **Catalog** (external, plural) | Discovery feeds we *read* and never edit: viva-catalog today, others later (BioSimulators, the multicellular ecosystems). Unvetted and unpinned | catalog (1), (4); the `/core` lists |
| **Registry** (ours) | The single record of **items**: package or source at a pinned version, module roots, the classes they provide, and OS/runtime requirements. Each item records its **curation per environment** (EV5). An ingest from the catalogs adds items at `listed`; promotion needs evidence | registry (1) + catalog (2) merged; `bundles:` → derived from environments; registry (5) retired |
| **Environment** (the island) | A named, versioned, locked runtime. **Composed** environments are computed from registry items by the forest (EV4) and defined in the workspace manifest (EV2). **Prebuilt** environments are an owner's image, registered by digest with the items it declares. **Sidecar** environments (EV13) are a special case. Its identity is the lock hash, then the digest (EV1) | environment (1), (3); `registry_env` (1); simulator (1), (2); bundle (1), (2); registry (2) retired into the workspace manifest |
| **Environment version / image** | One locked state of an environment (lock hash) and its built artifacts per platform (digests) | `SimulatorVersion`, `container_def_hash`; `environment_image` stays as the artifact table |
| **Interface** | What an environment version actually provides, read inside it (`pbg-interfaces/1`) | manifests per environment (already) |
| **Solver** (and future roles) | A role binding: a class in an environment that fills a role (TimeCourseSolver, …) | `solvers.yaml` (kept; keyed to the environment) |

**Rules that follow:**
- **"Simulator" means only an engine library or item kind** (COPASI, Smoldyn), never an environment. The
  `?simulator=` parameter becomes `?environment=`, with `simulator` kept as a deprecated alias for pbest and old
  clients. `Simulator` / `SimulatorVersion` become `EnvironmentVersion` in the model and API, behind a one-release
  alias.
- **`registry_env` stops being special.** It becomes an ordinary composed environment, renamed to say what it holds
  (e.g. `ode-ssa`, decided with EV4's first island list). Validation reads the placement (EV6), not a constant. The
  image repository becomes one per environment under one namespace (`ghcr.io/biosimulations/env/<name>`, EV12).
- **The registry is the only input to composed environments.** The vendored `biosimulations/registry`
  `registry.json` and pbest's library list are retired. A library enters an environment only as a registry item.
- **"Bundle" is dropped.** Membership is derived (an environment's items), and rule-2 bundles are just composed
  environments.
- **The UI page "Catalog" becomes "Registry"** (items, levels, environments). A catalog browser, if wanted, shows the
  external feeds marked as such.
- **"Island"** is the research metaphor for an environment in the forest. Code, API and UI keep the word
  **environment**.

**Migration** (staged, each step one PR):
1. Add `environment` alongside `simulator` in the API, labels and UI.
2. Make `bundles:` derived from environments.
3. Fold `catalog.yaml` into the registry as ingested `listed` items, keeping the generator as the ingest.
4. Rename `registry_env` once EV4 names its replacement, keeping the old name as an alias for stored runs and labels.
5. Retire `simulator_registry.json`, the `/core` lists and the legacy package tables.

Stored runs keep their old labels. Readers map old to new.

- **Alternatives.**
  - **Keep "simulator" for environments,** because pbest and the client already use it. Rejected: it is the main
    source of confusion, and an alias keeps compatibility.
  - **Keep catalog and registry as two files.** Workable, but then curation lives in two places with a precedence
    rule. One record with an ingest is simpler.
- **Consequences.**
  - Client and spec change: `?environment=`, and `EnvironmentVersion` types. That is the four-step release (or one,
    after decision 1).
  - pbest's operation names are unaffected. Only parameters gain aliases.
- **Status:** proposed. Other EVs assume it.

### EV1 — An island is a lock; its identity is the lock hash, then the image digest

- **Recommendation.**
  - An island is defined by a locked environment specification: one `pixi.lock` section per island and platform (EV2).
  - Before any image exists, its identity is the sha256 of that canonicalised section.
  - Once an image is built or pulled, the island also carries the image's **digest**. Runs record the digest.
  - This implements strategy decision 2 and retires `container_def_hash` (the md5 of the recipe) as identity.
- **Alternatives.**
  - Keep the recipe hash: rejected, because it does not reproduce (strategy §3).
  - Digest only: an island cannot be named, or probed for in a registry, before it is built. Galaxy's mulled hashing
    names first and probes second, and that pattern is the one to copy
    ([02 §prior art](environments/02-packaging-and-isolation.md)).
- **Consequences.**
  - Every existing `simulator` row is re-identified once.
  - `environment_image` already records sha256 per artifact, so it is the natural home for the digest.
  - pbest's template stops being the source of truth.
- **Status:** proposed. Gated by X6.

### EV2 — Islands are defined in one pixi workspace; uv inside it; Spack only where MPI stacks demand it

- **Recommendation.**
  - One workspace manifest, `islands/pixi.toml` (location to be decided), defines items as **features** and islands
    as **environments**.
  - conda-forge supplies the native stack: Python, MPI, PETSc, HDF5, BLAS, FEniCSx. PyPI items resolve through pixi's
    uv layer.
  - This is the pattern viva-pde-particle already ships end to end: its `compose` environment shares a solve-group
    with `default`.
- **Alternatives.**
  - **uv workspace on a conda base image.** It handles PyPI and git sources best and gives one universal lock. But
    the native layer becomes a second lock uv cannot see, and the result is not reproducible natively on laptops.
  - **Spack as the primary tool.** It has the strongest multi-version store and HPC story, but poor Python-simulator
    coverage and an expert-only user experience. Keep it for an HPC-native MPI island if one appears.
  - **Nix/Guix.** Strong reproducibility, but weak on macOS, Windows and HPC user experience.
- **Consequences.**
  - **pixi-build is preview.** Until it matures, source items come in as git or path PyPI dependencies, and their
    transitive `[tool.uv.sources]` must be mirrored by hand, because pixi does not read them.
  - **Rule for the conda/PyPI split.** Anything that links MPI, PETSc, HDF5 or BLAS comes from conda. PyPI supplies
    only self-contained wheels.
- **Evidence:** [02 §pixi](environments/02-packaging-and-isolation.md), [02 §uv](environments/02-packaging-and-isolation.md),
  [02 §Spack](environments/02-packaging-and-isolation.md).
- **Status:** proposed.

### EV3 — A common core, solved once, on every island

- **Recommendation.**
  - One `core` feature holds the middleware every island needs:
    - process-bigraph and bigraph-schema;
    - viva-emitters and viva-basic-processes;
    - bigraph-viz;
    - numpy, pyyaml and the viz libraries.
  - Every island that can take the common versions is placed in **one cross-island solve-group**, so shared items
    resolve identically.
  - An island leaves the group only when the solver proves it must. Its divergence is then explicit in the lock, and
    it is reported as skew (EV5).
- **Prerequisite.** `registry_env` moves to the modern core (process-bigraph ≥ 1.8; X5). The 1.0.5 pin comes from
  pbest 0.6.3's exact pins, so this is coupled to strategy decision 1 (consolidation).
  - Removing the pin, or consolidating, is the first step of this epoch, not the last.
- **Alternatives.**
  - Let every island float its own core: rejected. It defeats dedup (identical builds only) and makes cut-wire
    compatibility (EV8) the common case instead of the exception.
- **Consequences.**
  - The workbench and viva-superpowers go in a `dev` feature, never on islands that run jobs. That is the
    viva-pde-particle `compose` lesson.
  - EV14's upstream asks become prerequisites for a clean core.
- **Evidence:** [03 §common core, §shared middleware](environments/03-forest-algorithms.md).
- **Releases only for the core (2026-10-13, the user's direction).**
  - process-bigraph and bigraph-schema are pinned to **published releases**, never to git commits or branches, on
    every environment and in every manifest we own.
  - The one commit pin was a stopgap: viva-pde-particle pins process-bigraph `e5325c1` (`pixi.toml:67`,
    `pyproject.toml:13`). We pinned a commit rather than cut a release without the maintainer.
  - That pin is now covered: process-bigraph **1.9.1** (PyPI 2026-10-13, tag `v1.9.1` = `8ce2e1d`) contains `e5325c1`
    (GitHub compare: 7 ahead, 0 behind). 1.9.1 requires bigraph-schema ≥ 1.8.1.
  - The core target for X5 and EV3 is therefore **process-bigraph ≥ 1.9.1 / bigraph-schema ≥ 1.8.1**.
  - When we need an unreleased core change, we ask for a release rather than pin a commit.
  - Moving viva-pde-particle to 1.9.1 is a vivarium-collective change, so it is made with the user's go-ahead (EV14).
- **Status:** proposed. Gated by X5.

### EV4 — The forest is computed: a cover driven by demand, with the solver as oracle

- **Recommendation.**
  - **Elements to cover.** The composites people run, plus curated combinations: G1's composite, the SED-ML suites,
    and catalogue studies.
  - **Candidate sets.** Islands that lock.
  - **Greedy rounds.** Each round grows an island by adding the items that cover the most uncovered composites, until
    `pixi lock` refuses. Then a new island starts. This is the Spack `when_possible` pattern applied across islands
    rather than inside one.
  - **Cost.** Islands first; distinct builds (bytes not shared) as the tie-breaker.
  - **Conflict explanations.** Every refusal's explanation (resolvo/uv) is stored as a minimal conflicting set: the
    "why not together" data that exists nowhere today.
  - **Recompute** when the manifest, the catalog or the demand set changes. The output is the island list in the
    workspace manifest, reviewed as a PR.
- **Alternatives.**
  - Pairwise conflict graph and colouring (Tate & Yuan): a cheap pre-filter, but unsound alone, because three items
    can conflict when no pair does.
  - Hand-declared solve-groups: today's practice, which does not scale.
  - Exact ILP or ASP: viable at our scale (tens of items). Keep it as a check on the greedy result.
- **Evidence:** [03 §algorithms](environments/03-forest-algorithms.md).
- **Status:** proposed. Gated by X1.

### EV5 — Curation and interfaces are per (entry, version, island)

- **Recommendation.**
  - A registry entry keeps one identity, but its **level**, its **interface manifest** and its **resolved version**
    are recorded per island.
  - Interface manifests are already per environment (`registry/manifests/<env>.json`).
  - `bundles` becomes the island list.
  - Validation resolves an address against the islands named by the placement (EV6), instead of the hard-coded
    `SERVICE_BUNDLE`.
  - Skew (one entry at different versions on different islands) is reported, never silent.
- **Consequences.**
  - This is a manifest schema change, plus changes to `manifest.py`, `validation.py` and the `/registry/environments`
    API.
  - The web UI's checker reads the per-island interface.
- **Evidence:** [03 §version skew](environments/03-forest-algorithms.md), [01 §registry](environments/01-current-state.md).
- **Status:** proposed.

### EV6 — Placement is a map on the composite; a partitioner fills it in

- **Recommendation.**
  - Addresses stay `local:module.Class`. A composite may carry a **placement map** from node path to island, and a
    partitioner fills in what is missing, in this order:
    1. version pins (an item may only go to islands whose version satisfies the composite's pin);
    2. co-location (one island if possible: rule 1);
    3. **producer fusion** for adapters, IO and data processing;
    4. viz and plotting at the consumer or coordinator when they read emitted history;
    5. min-cut on the estimated bytes per tick over cut wires.
  - An explicit pin always wins.
- **Alternatives.**
  - Island-bearing addresses (`island:<name>/local:…`): rejected. It ties documents to deployment and breaks every
    existing document.
- **Evidence:** [04 §placement](environments/04-coupling-and-execution.md).
- **Status:** proposed.

### EV7 — One worker protocol: a stdio "kernel", launched by an adapter per platform

- **Recommendation.**
  - **Verbs.** An isolated island runs a `pbg-worker` that speaks length-framed **msgpack** RPC on stdin/stdout, with
    stderr for logs: `describe` (items, versions, port schemas and their hashes, protocol version), `initialize`,
    `update(state, interval)`, `end`, `heartbeat`, `interrupt`. These are the Jupyter-kernel and MCP/LSP patterns.
  - **Large arrays** travel out of band: shared memory on one host, a side socket otherwise.
  - **The launcher** is the only per-platform part:
    - `python -m`;
    - `pixi run -e <island>`;
    - `docker run -i --rm` / `podman` / Apple `container`;
    - `apptainer exec <sif>`;
    - `srun … apptainer exec`.
  - **Build on, don't invent.** Generalise process-bigraph's `git:` worker (per-SHA uv venv, stdlib NDJSON over
    stdio), proposed upstream as a protocol of its own.
- **Why stdio.** It passes unchanged through `docker -i`, `apptainer exec`, `ssh` and `srun`, and it works on all four
  platforms.
  - asyncio Unix sockets do not exist on Windows.
  - Ray's container environments need Podman and are experimental.
  - MPI spawn is fragile under SLURM.
- **Evidence:** [04 §IPC, §candidate architecture A](environments/04-coupling-and-execution.md).
- **Status:** proposed. Gated by X3.

### EV8 — State crosses islands as schema-described data, checked at handshake

- **Recommendation.**
  - Cut-wire state is serialised through bigraph-schema (`serialize`/`realize`) into msgpack, or into Arrow IPC for
    tables, tensors and variable-length populations.
  - Each port's canonical schema has a hash. At handshake the coordinator compares the two sides of every cut wire:
    identical passes; otherwise a compatibility rule decides (backward or full, as in Avro and Confluent).
  - **No pickle across islands.** NumPy 2 pickles do not load in NumPy 1, and pickle executes code.
- **Consequences.**
  - Wire compatibility depends on port schemas, not item versions. A shared item at two versions is fine when its
    ports agree. Behaviour differences become provenance (the version per placement is recorded), not a transport
    error.
- **Evidence:** [04 §wire compatibility](environments/04-coupling-and-execution.md), [03 §version skew](environments/03-forest-algorithms.md).
- **Status:** proposed.

### EV9 — Multi-node HPC: evaluate MUSCLE3 behind the EV7 verbs; a pilot for many small workers

- **Recommendation.**
  - **Single node:** EV7 alone suffices.
  - **Multi-node:** evaluate MUSCLE3. Compile a placed composite to yMMSL, with each island worker a MUSCLE3
    component (`apptainer exec <sif> pbg-muscle-worker`), and keep the EV7 verbs as the component body. That gains
    SLURM placement, MPI, peer-to-peer data and checkpointing.
  - **Many small workers in one allocation:** HyperQueue (no privileges needed) or Flux.
- **Risks.** MUSCLE3 requires an identical libmuscle in every container, and its laptop and Windows story is
  unconfirmed. So it is a backend, never the only path.
- **Evidence:** [04 §MUSCLE3, §pilots](environments/04-coupling-and-execution.md).
- **Status:** deferred until X4.

### EV10 — Share the overlap physically

- **Recommendation.**
  - **OCI:** a shared base image (OS, Python, the EV3 core), with per-island layers on top, so that registry and pull
    caches deduplicate by digest.
  - **HPC:** a base SIF plus per-island read-only overlays (or Apptainer 1.6 `build --overlay`), *or* islands as
    pixi environments on the shared store, bind-mounted into a thin runtime. X2 decides between them.
  - Dedup only works for identical builds, which is why EV3 matters.
- **Evidence:** [02 §containers](environments/02-packaging-and-isolation.md), [03 §physical sharing](environments/03-forest-algorithms.md).
- **Status:** proposed. Gated by X2.

### EV11 — Platform tiers

- **Recommendation.**

  | Tier | Platform | Islands | How |
  |---|---|---|---|
  | 1 | HPC (SLURM, Apptainer) | all | SIF from the OCI image; EV9 for multi-node |
  | 1 | Linux laptop/server | all | native pixi, or OCI |
  | 2 | macOS arm64 | all that lock for `osx-arm64` | native pixi first; linux/arm64 images otherwise (never amd64 under Rosetta: FEniCS fails on AVX) |
  | 3 | Windows | the subset that locks for `win-64` | native pixi; WSL2 or containers for the rest; no Apptainer |

  - The forest computation (EV4) runs per platform. An island missing on a tier is reported, not hidden.
- **Evidence:** [05](environments/05-platforms.md).
- **Status:** proposed.

### EV12 — Islands are registered, versioned, published and retained

- **Recommendation.** This is epoch 1's phase 5, resumed.
  - An island version is (name, lock hash, digest per platform).
  - Images are pushed by digest to `ghcr.io/biosimulations/…`, with SIFs as ORAS artifacts, and recorded as
    `environment_image` rows of kind `oci`/`oras`.
  - Islands are write-once (E4). An island version is retained while any result references it.
  - A cluster pulls by digest instead of building.
- **Status:** proposed. Gated by X6.

### EV13 — Non-Python and research islands are sidecars behind the same protocol

- **Recommendation.**
  - Items that pip and conda cannot express are **sidecar islands**: Node (Artistoo), Java (comets), Docker-only C++
    (Chaste, tstmd), compile-per-model (PhysiCell), and runtime compilers (AMICI). Each is a prebuilt image whose
    entrypoint speaks EV7.
  - Multicellular coupling needs **mapping adapters as registry items**, such as lattice↔agent and voxel↔centroid,
    cell id↔agent id. It also needs **variable-length port types** (Arrow tables) for changing populations.
  - OpenMP and GPU codes get one long-lived worker owning many cores or a GPU.
- **Evidence:** [06](environments/06-research-islands.md).
- **Status:** proposed.

### EV14 — Upstream asks (we ask; we do not change vivarium-collective repositories ourselves)

The asks:
1. Publish `viva-basic-processes` to PyPI. vivarium-workbench 0.4.1 requires it, and it is not there.
2. Settle one distribution name per package and retire the `pbg-*` aliases. Git `pbg-superpowers.git@main` resolves
   to a package named `viva-superpowers`.
3. Replace git `main` sources with versioned releases. 38 of 50 pyprojects use them; only viva-pde-particle pins SHAs.
4. Stop listing vivarium-workbench as a runtime dependency of wrappers (21 do).
5. process-bigraph: schema-aware serialisation in the `git:` and `rest:` transports (EV8). (A suspected result bug in
   `parallel.py` was checked and is not one: `send_command` sets `_pending_command` through the inherited
   `pre_send_command`; see [01](environments/01-current-state.md).)
6. viva-pde-particle: replace the process-bigraph commit pin (`e5325c1`) with the release `process-bigraph>=1.9.1`, which
   contains it (EV3, releases only). This is our own work there, but it is a vivarium-collective repository.

- **Status:** proposed. Each ask is raised only with the user's go-ahead.

### EV15 — The authoring environment is decoupled from the run environments, with bounded core skew

**Question.** Must the environment that *authors and checks* composites run the same process-bigraph as the
environments that *run* them?

**What is true today:**
- **Authoring already runs in its own environment.** The DSL and SED-ML translation (process-bigraph-lang, the
  checker; the SED2 work builds on the same) run as a CLI in a separate venv (`.pblang`, `settings.pblang_python`,
  `sedml/pblang-requirements.txt`: `process-bigraph-lang==0.3.1`).
- process-bigraph-lang 0.3.1 depends on **bigraph-schema ≥ 1.6, < 2** and numpy only, **not on process-bigraph**.
- **It never imports the run environments' packages.** It reads their **interface manifests** (`pbg-interfaces/1`
  JSON, produced *inside* each image by the standard-library describe script).
- **The skew is already being tolerated.** The API's own environment runs process-bigraph 1.0.5 / bigraph-schema
  1.0.14, and the two run environments run 1.0.5 and 1.8.5. The checker serves both through manifests.

**Recommendation.** Make that a rule, with a bound:
1. **The authoring environment is its own environment** in the forest (an `authoring` island), versioned and locked
   like the others. It is never merged into a run environment and never imports run-environment packages.
2. **The contract between them is the manifest, not the package.** Authoring depends on the manifest format version
   (`pbg-interfaces/N`) and the bigraph-schema *type language* used in port and config schemas, not on matching
   process-bigraph versions.
3. **Tolerated skew:**
   - any process-bigraph version on a run environment;
   - a bigraph-schema **major** version shared by authoring and the manifests it reads;
   - a manifest format version authoring declares it supports.

   Outside that bound the checker refuses with a clear message ("environment X's manifest uses pbg-interfaces/2;
   this checker reads /1"), rather than checking wrongly.
4. **What the checker cannot see is checked later, where it can be seen.**
   - Behaviour that depends on the run-side process-bigraph (scheduling, update semantics: e.g. the open
     process-bigraph#240 chunking issue) is not a manifest property.
   - It is covered by the target environment's own suites (EV5 curation) and by EV8's schema-hash handshake at run
     time.
5. Every manifest records the producing environment's process-bigraph and bigraph-schema versions (they already
   record Python), so a skew is visible at authoring time.

**Alternatives.**
- **One core everywhere, authoring included.** Rejected. It would force the checker to move in lockstep with the
  oldest run environment, which is exactly the 1.0.5 trap. It would also make authoring import heavy simulator
  stacks.
- **Authoring imports the target environment** (run the checker inside each image). Rejected as the default:
  - it needs every image locally;
  - it is slow;
  - it breaks laptop authoring on Windows and macOS.

  Keep it as the describe step, which is what produces the manifest.

**Consequences.**
- EV3's common core binds the *run* environments only. Authoring follows bigraph-schema majors.
- The manifest format becomes a versioned, published contract with a compatibility policy, like EV8's wire schemas.
- The web UI and the CLI check against the selected environment's manifest version.

**Evidence:**
- `compose_api/config.py` (`pblang_python`), `sedml/pblang-requirements.txt`;
- [plan-authoring.md](plan-authoring.md), `registry/environments.yaml`, `registry/manifests/*.json`;
- [01 §current state](environments/01-current-state.md).

**Status:** proposed.

## Experiments (each gates a decision)

| | Experiment | Gates | Done when |
|---|---|---|---|
| X1 | Lock every catalogue item alone, every pair, and the greedy islands, with pixi, for `linux-64`, `osx-arm64` and `win-64`; harvest the conflict explanations | EV4, EV11 | a committed matrix and a first island list |
| X2 | On Mantis: a base SIF plus two stacked read-only overlays; a pixi environment on the shared store bind-mounted into a thin SIF; compare start time and disk | EV10 | a measured choice |
| X3 | A `pbg-worker` prototype: one process in another island, driven over stdio via `python`, `docker run -i` and `apptainer exec`, on macOS, Linux and Windows | EV7, EV8 | the same composite result on all three launchers |
| X4 | MUSCLE3: the X3 worker as a MUSCLE3 component in two SIFs across two nodes under SLURM | EV9 | a run, plus the measured overhead per exchange |
| X5 | `registry_env` on process-bigraph ≥ 1.9.1 / bigraph-schema ≥ 1.8.1 (releases only): its manifest suites and the SED-ML suites still pass | EV3 | suites green, or a list of breaks |
| X6 | Lock hash → build → digest → pull by digest on the cluster; identical digest on rebuild where the inputs are pinned | EV1, EV12 | round trip demonstrated |

## Phases

| Phase | Content | Depends on |
|---|---|---|
| E2.0 | These documents; EV0 migration steps 1–3 (`environment` alongside `simulator`, derived membership, catalog folded into the registry); X1, X5; EV14 asks raised (with permission); EV15 rule 5 (manifests record the core versions) | — |
| E2.1 | EV0 steps 4–5 (rename `registry_env`, retire the library list and legacy tables); islands in one pixi workspace (EV2, EV3); identity by lock hash and digest (EV1); registry per island (EV5) | X1, X5, X6 |
| E2.2 | Worker protocol and wire format (EV7, EV8); placement (EV6); sidecar islands (EV13) | X3 |
| E2.3 | HPC sharing (EV10); multi-node backend (EV9) | X2, X4 |
| E2.4 | Publish and retain (EV12); platform tiers in CI (EV11) | E2.1 |

**Relation to strategy:**
- **Rule 1 (one environment per composite)** becomes "one island per composite where possible" (EV6, step 2).
- **Rule 2 (cached bundles)** is EV4's output.
- **Rule 3 (split across containers)** is EV7 with EV6. That is grant row `A3.4.docker`.
- **Decision 1 (consolidation)** is coupled through EV3's prerequisite.
- **Decision 2 (digest identity)** is EV1.

## Open questions
1. Where does the island workspace live: in compose-api, in a registry repository, or in a consolidated toolkit
   (decision 1)?
2. Who owns the demand set for EV4? It could be the curated composites, the suites, or the catalogue's studies.
3. Does Mantis offer Enroot/Pyxis, or Apptainer's OCI mode? The plan-container-runtimes §6 questions to the
   administrators are still unasked.
4. Do we accept pixi-build while it is preview, or wait and mirror git sources by hand?
5. Is MUSCLE3's identical-version constraint acceptable across islands we do not build ourselves (prebuilt owners)?
