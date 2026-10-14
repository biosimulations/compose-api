# The forest: an overlapping cover of compatible islands

**Status (as of 2026-10-13): research, no decisions.** This chapter states the problem of choosing environments for
composites, surveys algorithms for it, and records what the vivarium-collective catalogue says about the shared
middleware that every choice must accommodate. Tools are in chapter 02.

**Verification.** A claim with a URL or a repository path was read there on 2026-10-13, by this chapter's author or by
the research pass it draws on. *(unverified)* marks memory or inference. *(inference)* marks reasoning offered as a
proposal. The Spack `when_possible` algorithm (§4.4) and uv's conflict forking (§4.5) were re-checked at source for
this chapter.

## 1. Problem statement and vocabulary

| Term | Meaning |
|---|---|
| **Item** | Anything an environment must provide: a package, a step, a process, a composite, or an OS dependency (MPI, a JVM, Node, a compiler) |
| **Island** | A locked environment: one resolved set of items, identified by its lock section and, once built, its image digest |
| **Member** | An item resolved inside an island, at a specific (version, build) |
| **Demand** | A composite (or common pairing) people actually run; it must fit entirely inside at least one island, or be split across islands by placement |
| **Cover** | The set of islands; together they must host every demanded composite |
| **Core** | Items every island holds (§5) |

**It is a cover, not a partition.** The same item appears in many islands. Common middleware (adapters, solvers, IO,
viz, data processing; §8) is wanted everywhere, and a popular simulator may sit in several islands next to different
partners. A partition (each item in exactly one island) is the special case Spack's rounds and graph coloring produce
(§4); a cover lets an item be repeated wherever demand needs it.

**Today (2026-10-13)** compose-api has two islands, chosen by the submitter, not derived from the document
(`simulation/handlers.py:77-81`):

| Island | Kind | Python | process-bigraph | bigraph-schema |
|---|---|---|---|---|
| `registry_env` | shared, generated from `simulator_registry.json` | 3.12.15 | 1.0.5 | 1.0.14 |
| `viva-pde-particle` | prebuilt, pinned by digest | 3.12.13 | 1.8.5 | 1.7.0 |

(`compose_api/registry/manifests/*.json`.) There is no dependency graph, resolver or conflict record; pbest
concatenates install lines without resolving them (`container_constructor.py:51-68`). Strategy plans one environment
per composite (rule 1), cached bundles of popular combinations (rule 2), then splitting across containers (rule 3)
(`docs/strategy.md:283-296`).

## 2. Two objectives

Let *D* be the demanded composites, each a set of items, and *solve(S)* the resolver's verdict on item set *S*.

| Objective | Minimise | Drives | Pulls toward |
|---|---|---|---|
| **A. Fewest islands** | number of islands such that every *d* ∈ *D* fits inside one | builds, images to keep, placement choices, curation runs (one per island) | big islands, many items each |
| **B. Fewest distinct builds** | distinct (package, version, build) triples across all islands | storage, shared-layer reuse, how much of a result is reproducible from shared parts, version skew (§7) | islands that agree on shared items, even at the cost of more islands |

They conflict *(inference)*: packing more items into one island raises the chance that the solver picks different
versions of shared items than in other islands (worse B); keeping shared items identical everywhere may force
incompatible partners apart (worse A). A useful combined cost is *islands × fixed cost + Σ unshared bytes*, with demand
weights so rare composites do not shape the cover.

## 3. Why pairwise compatibility is necessary but not sufficient

- **Necessary.** If *solve({a, b})* fails, no island holds both *a* and *b*.
- **Not sufficient.** Three items can co-install in every pair and still fail together. Example *(constructed)*: *a*
  accepts `lib` 1 or 2, *b* accepts 2 or 3, *c* accepts 1 or 3. Pairs resolve on 2, 3 and 1; the triple has no
  version. Transitive dependencies make this common in practice: each pair agrees on a different version of a shared
  transitive dependency.
- **Downward-closed.** For a complete solver, any subset of a feasible set is feasible: a solution for *S* is a
  consistent install set for any subset *(inference; incomplete resolvers, such as a backtracking timeout, can break
  this)*. So the feasible sets form an independence system, and infeasibility is fully described by the **minimal
  infeasible sets** (conflict hyperedges). Pairwise conflicts are only the hyperedges of size 2.
- **Consequence.** A pairwise conflict graph is a cheap filter. Every candidate island must still be confirmed with a
  full joint solve, on every platform it targets.

## 4. Algorithms

### 4.1 Cliques in a compatibility graph

- Nodes are items; an edge means the pair resolves (N²/2 solves, each cheap: `uv pip compile`, a pixi or rattler dry
  solve).
- Maximal cliques (Bron–Kerbosch) are candidate islands; each needs a joint solve (§3).
- Cheap to bootstrap; maximal cliques can be exponentially many; unsound on higher-order conflicts. Heuristic only.

### 4.2 Maximal satisfiable / minimal correction subsets, from solver explanations

- Treat "the resolver succeeds on *S*" as satisfiability over item-selection variables. The **maximal satisfiable
  subsets** (MSS) are maximal islands; their complements are the **minimal correction subsets** (MCS); the **minimal
  unsatisfiable subsets** (MUS) are the minimal conflict sets, "why these cannot share". MCSes are the minimal hitting
  sets of the MUSes; MARCO-style enumeration (Liffiton et al.) produces both *(unverified)*.
- **Our solvers already explain failures.** uv uses a PubGrub-derived resolver
  ([uv resolution](https://docs.astral.sh/uv/concepts/resolution/)), whose error is a derivation of incompatibilities;
  pixi uses resolvo, a CDCL solver ([prefix.dev blog](https://prefix.dev/blog/pixi_a_fast_conda_alternative)); Spack
  uses clingo, which can report unsatisfiable cores *(unverified as exposed by Spack)*. Harvesting the items named in a
  failure gives a (not necessarily minimal) conflict set; shrinking it with a few re-solves gives a MUS
  *(inference)*.
- **Output worth keeping regardless of algorithm:** a table of conflict sets with the solver's reason. No such data
  exists anywhere today (current-state research, "Gaps and unknowns").

### 4.3 Demand-driven greedy set cover (recommended framing)

- Elements to cover: the demanded composites *D*. Candidate sets: feasible islands. An item may appear in any number of
  them: the overlap.
- Minimising the number of sets is NP-hard; the greedy rule, repeatedly take the set covering the most uncovered
  elements, is an ln(n) approximation *(standard result; unverified citation)*.
- The solver is the **feasibility oracle**; candidate islands are grown, not enumerated *(inference)*:

```text
uncovered = D (weighted by demand)
while uncovered:
    I = core ∪ items(heaviest uncovered composite)      # must solve, else that composite is quarantined (§5)
    for d in uncovered by weight, descending:
        if solve(I ∪ items(d)) on every target platform: I = I ∪ items(d)
    prefer, among equal growth, the d adding fewest new (pkg, version, build) triples   # objective B
    emit island I; uncovered -= {d ⊆ I}
```

- Weighting by unshared bytes gives objective B; demand weights keep rare composites from shaping big islands.
- Matches strategy rules 1–2 (`docs/strategy.md:283-296`): a composite's own island first, cached bundles of popular
  combinations next.
- Re-run when `registry/manifest.yaml` or demand changes; keep existing islands as preferred candidates so the cover is
  stable (write-once images, decision E4).

### 4.4 Spack `unify: when_possible` rounds (verified)

- **What the source says** (spack `develop`, 2026-10-13). `when_possible.lp` lets clingo choose
  `{ solve_literal(ID) }` per input spec, requires at least one, and `#minimize`s at high priority
  `"number of input specs not concretized"`, so each solve concretizes the **largest set of roots that fit together**
  ([when_possible.lp](https://github.com/spack/spack/blob/develop/lib/spack/spack/solver/when_possible.lp)).
  `solve_in_rounds` ([asp.py](https://github.com/spack/spack/blob/develop/lib/spack/spack/solver/asp.py)) repeats on
  the unsolved roots, adding every spec solved so far to the reusable set ("Each round tries to maximize the reuse of
  specs from previous rounds"), and raises if a round solves nothing.
- **Reading for us.** Each round is one compatible group: a greedy, maximum-cardinality-first partition. Reuse of
  earlier rounds' specs pushes later groups toward the same builds, so objective B is built in. It handles
  higher-order conflicts correctly because each round is a joint solve, with no pairwise precomputation.
- **Limits.** A partition, not a cover (each root lands in one round); no demand weights; not guaranteed fewest groups;
  all rounds live in **one** Spack environment that may hold duplicate versions
  ([environments](https://spack.readthedocs.io/en/latest/environments.html)), not in separate islands.
- **Portable idea.** "Solve the largest subset" is native to an optimising ASP solver; with uv or pixi it needs
  iterative removal driven by the conflict explanation (§4.2) *(inference)*.

### 4.5 Expressing the result: pixi features and solve-groups, uv conflicts

These **record** a cover; they do not compute one.

- **pixi.** Features are "reusable parts that can be shared between environments"; an environment is a list of
  features; a `solve-group` makes grouped environments take identical versions of shared packages
  ([multi-environment](https://pixi.prefix.dev/latest/workspace/multi_environment/)). So: core = one feature included by
  every island; islands = environments; islands that agree on the core = one solve-group; an island that cannot agree
  = its own group, its skew visible in `pixi.lock`. pixi itself is the oracle: locking an environment either succeeds
  or reports a conflict.
- **uv.** `tool.uv.conflicts` marks extras or groups mutually exclusive; they are "resolved in different forks so that
  they cannot conflict with one another", and installing both fails
  ([settings](https://docs.astral.sh/uv/reference/settings/)). One `uv.lock` can carry several PyPI-only islands.
- **Spack.** `include_concrete` composes environments from other locks; views with projections expose each island from
  one store ([environments](https://spack.readthedocs.io/en/latest/environments.html)).

### 4.6 Tate & Yuan: minimum build environment sets as graph coloring

- Tate & Yuan (2022), "Minimum Size Build Environment Sets and Graph Coloring"
  ([paper](https://scitepress.org/PublishedPapers/2022/112632),
  [project](https://www.uncg.edu/cmp/faculty/srtate/pubs/buildenv)): items are vertices, conflicts are edges, the
  fewest environments is the chromatic number. They build the conflict graph from package metadata, simplify it, and
  colour heuristically.
- Result on Ubuntu: 4 environments for the 1000 most popular source packages, 11 for all 30,646.
- The direct precedent for objective A. Exact only for pairwise conflicts (§3); yields a partition; colour classes
  still need joint solves (split any that fail).

### 4.7 COINST: co-installability kernels

[COINST](https://www.irif.fr/~vouillon/coinst/) (Mancoosi/EDOS line) computes and visualises co-installability
kernels, the strong conflicts, of Debian. Useful as a model for **reporting** conflicts to curators: collapse items that
always co-install with the same partners, show the conflicts between the classes.

### 4.8 Python dependency-conflict literature

| Work | Contribution |
|---|---|
| [Watchman (ICSE 2020)](https://2020.icse-conferences.org/details/icse-2020-papers/110/Watchman-Monitoring-Dependency-Conflicts-for-Python-Library-Ecosystem) | 235 real conflict issues; monitors PyPI for new ones |
| [smartPip (ASE 2022)](https://conf.researchr.org/details/ase-2022/ase-2022-research-papers/115/SmartPip-A-Smart-Approach-to-Resolving-Python-Dependency-Conflict-Issues) | revisits conflicts under pip's backtracking resolver |
| [PyEGo (ICSE 2022)](https://conf.researchr.org/details/icse-2022/icse-2022-papers/90/Knowledge-Based-Environment-Dependency-Inference-for-Python-Programs) | knowledge-graph inference of interpreter, system and library versions |
| [arXiv 2201.07029](https://arxiv.org/pdf/2201.07029) | conflict-aware inference: DFS with backtracking, SAT fallback |
| [ModuleGuard](https://arxiv.org/abs/2401.02090) | module-name clashes: two distributions, one import name |
| [PLLM (arXiv 2501.16191)](https://arxiv.org/pdf/2501.16191) | LLM-based repair of dependency errors |
| [arXiv 2506.10803](https://arxiv.org/pdf/2506.10803) | dependency resolution on hypergraphs |

None chooses a set of environments; they detect, explain or repair conflicts within one.

### 4.9 Summary

| Algorithm | Higher-order conflicts | Cover or partition | Demand-aware | Cost | Role |
|---|---|---|---|---|---|
| Cliques | No (needs joint solve) | Cover | No | N² solves + enumeration | bootstrap |
| MSS/MUS enumeration | Yes | Cover (all maximal islands) | No | many solves; exponential worst case | conflict data |
| Greedy set cover + oracle | Yes | Cover | Yes | ~one solve per (island, candidate) | **main loop** |
| Spack rounds | Yes | Partition | No | one optimising solve per round | ready-made, Spack only |
| Tate & Yuan colouring | No | Partition | No | N² + colouring | lower bound on A |
| Exact ILP/ASP | Yes | Either | Yes | fine at a few dozen items *(inference)* | check on the greedy result |

## 5. The common core as a base feature

- **Core** = the items every island must hold: process-bigraph, bigraph-schema, the emitters and adapters, viz, numpy
  and IO (§8). Model it as a base feature included in every island, not as an ordinary member of the cover.
- Give core items **wide version ranges** where safe, so they do not split islands; fix them within a solve-group so
  islands agree (objective B).
- **Order the checks so common-component conflicts are found first** *(inference)*; they are the most expensive,
  because they block an item from every island:

| Step | Solve | Finds | Cost |
|---|---|---|---|
| 1 | core alone, per platform | the core is itself consistent | 1 per platform |
| 2 | core ∪ {item}, for each item | items that conflict with the core: fix their pins, or quarantine them in a prebuilt island with its own core (explicit skew, §7) | N |
| 3 | core ∪ {a, b}, for pairs among survivors | pairwise conflicts beyond the core | ≤ N²/2, prunable by demand |
| 4 | core ∪ candidate island (§4.3) | higher-order conflicts | one per candidate |

- Step 2 is also the curation test (inference): an item at level `tested` is tested inside an island, and the core is
  the part of every island it must survive.

## 6. Physical sharing of the overlap

**Rule: every mechanism deduplicates only identical builds.** Disk savings depend on islands agreeing on versions, so
skew costs storage as well as reproducibility.

| Mechanism | Unit shared | Constraint | Fit for SLURM + Apptainer |
|---|---|---|---|
| Spack install tree + views | one prefix per full DAG hash; "a single installation ... re-used across multiple environments" | a differing dependency means a new hash, a new prefix | good when the tree is on the shared filesystem; per-island views are cheap |
| conda/pixi package cache | an extracted package, hard-linked (or reflinked) into each prefix *(unverified for pixi)* | cache and environments on one filesystem, else copies | fine for building; hardlinks on NFS/GPFS unknown |
| uv cache | wheel contents; `clone` on macOS/Linux, `hardlink` on Windows ([settings](https://docs.astral.sh/uv/reference/settings/)) | same filesystem, else a slow copy | as conda; PyPI only |
| OCI layers | content-addressed blobs, shared in registry and pull cache | identical bytes; shared items must sit in a common base or layer prefix | registry-side only |
| Apptainer SIF | nothing between SIFs | each island's SIF copies the core in full | **today's duplication** |
| Apptainer overlays | a base SIF + per-island overlay; ext3 or embedded; 1.6 `build --overlay` records the base's hash ([CHANGELOG](https://github.com/apptainer/apptainer/blob/main/CHANGELOG.md)) | stacking several overlays *(unverified)*; 1.6 unreleased | a "core" SIF + per-island overlays shares the core on disk |
| Shared store bind-mounted into a thin runtime (CVMFS/EESSI pattern) | a Spack tree or pixi environments on the shared filesystem | identity must come from the store's own hashes, or it breaks digest identity (strategy decision 2) | most storage-efficient; least like "the image is the environment" |

## 7. Version skew of a shared item across islands

An item in two islands may resolve to two versions. That is legitimate, and already true of the core (§1), but every
place that names an item must then also name the island.

1. **Identity.** An item's identity becomes (entry, resolved version, build) plus island. A registry entry carries one
   pin (`compose_api/registry/manifest.py:56-60`) and a list of `bundles` (`:52`), so overlap is representable, but the
   model implies one version everywhere. Module → entry lookup (`manifest.py:74-81`) must also know the island.
2. **Curation.** A level is a fact about (item version, island): *tested* means its suite passes in that environment
   (`docs/strategy.md:247-265`). Interface manifests are already per environment (`registry/manifests/<env>.json`).
3. **Addresses.** `local:pkg.Class` names neither island nor version. A composite spanning islands needs a placement:
   a protocol carrying the island digest, or a composite-level placement map. The validator accepts only `local` and
   only `registry_env` (`registry/validation.py:104-129`); prebuilt submissions skip it
   (`api/routers/simulation.py:108-121`).
4. **Wire compatibility.** Across an island boundary the sides may run different bigraph-schema versions (1.0.14 vs
   1.7.0). No transport today uses schema `serialize`/`realize`; all send raw JSON or pickle (current-state research
   §4). Prior art: MUSCLE3 refuses to start on a libmuscle version mismatch
   ([containers](https://muscle3.readthedocs.io/en/latest/containers.html)); FMI 3.0 checks `fmiVersion` and an
   instantiation token *(unverified detail;* [spec](https://fmi-standard.org/docs/3.0)*)*; Avro resolves writer against
   reader schemas ([Resolver](https://avro.apache.org/docs/1.12.0/api/java/org/apache/avro/Resolver.html)); Confluent's
   registry has BACKWARD, FORWARD, FULL and `_TRANSITIVE` modes
   ([schema evolution](https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.md)).
   Implication *(inference)*: give each port type a canonical serialised schema and hash; at handshake each island
   reports `(item@version, port schema hashes, bigraph-schema version)`; the coordinator checks each cut wire is
   identical or compatible in the BACKWARD/FULL sense. Two versions of one item on two islands are then fine if their
   port schemas agree. Never pickle across islands.
5. **Reproducibility.** A spanning run's identity is the set of island digests, the placement map and the wire-protocol
   version. Every process in a result records its island digest and resolved version. Write-once images (decision E4)
   keep old islands retrievable only if each island a result used is retained and pinned by digest. One shared item
   (a plotting step, say) may run at two versions in one run; record that as skew, do not discover it later.
6. **Policy option** *(inference)*. Put the core in one cross-island solve-group so shared items resolve identically by
   default; allow a different version only when the solver proves an island cannot take the common one (step 2 of
   §5), and record the exception. Skew stays rare and visible, and dedup by hash is maximised.
7. **Placement constraint.** A component may run only on islands whose version satisfies the composite's pin, which
   restricts which island hosts a replicated item (coupling research, §7 Q1–Q2).

## 8. Shared middleware in the viva catalogue

Method (research pass, 2026-10-13): parsed `project.dependencies`, extras, dependency-groups and `[tool.uv.sources]` of
50 catalogue pyprojects from default branches; current versions and dependencies from the PyPI JSON API
(`https://pypi.org/pypi/<name>/json`).

| Shared item | Repos (of 50) | Declared spread | Source form | Latest on PyPI (its core floor) |
|---|---|---|---|---|
| process-bigraph | 49 (main) | `*` 7; `>=0.0.10` 11; `>=0.0.30`, `>=0.0.38` 1 each; `>=0.0.66` 10; `>=1.0` 1; `>=1.4.12` 3; `>=1.5.0` 2; `>=1.7.0` 1; `>=1.8.3` 1; `>=1.8.5` 10; one SHA pin | 47 PyPI, 2 git main | 1.9.1 (bigraph-schema>=1.8.1) |
| bigraph-schema | 47 | `*` 27; `>=0.0.60` 16; `>=1.0` 1; `>=1.4.3` 1; `>=1.4.4` 2 | 45 PyPI, 2 git main | 1.8.1 |
| bigraph-viz (viz) | 35 (18 main, 24 extras) | `*` 23; `>=2.0.3` 17; others 2 | PyPI | 2.0.3 (process-bigraph>=1.2.2) |
| matplotlib / plotly (viz) | 36 / 26, mostly extras | almost all `*` | PyPI | — |
| viva-superpowers | 17 | `*` | 15 git main, 1 bare git, 1 PyPI | 0.23.0 (process-bigraph>=1.8.2) |
| pbg-superpowers (old name) | 8 | `*`, one `>=0.16` | 5 git `pbg-superpowers.git@main`, 1 git viva-superpowers, 2 PyPI | 0.23.0 shim → viva-superpowers>=0.23.0 |
| vivarium-workbench (a web app as runtime dependency) | 21 (15 main, 6 extras) | `*` | 15 git main, 2 bare git, 1 `../` path, 1 `vivarium-dashboard.git`, 2 PyPI | 0.4.1 (process-bigraph>=1.8.4, bigraph-schema>=1.7.0, zarr>=3.1.6, xarray>=2026.04) |
| viva-emitters (IO) | 4 direct, plus transitively via superpowers/workbench | `>=0.4.2` 3; one bare git | PyPI | 0.4.3 (process-bigraph>=1.4.12) |
| viva-basic-processes (adapters) | 3 direct, plus transitively via workbench | none | **not on PyPI**; PyPI has only `pbg-basic-processes` 0.3.0 | — (pbg-basic-processes: process-bigraph>=1.4.12) |
| data/IO (pyyaml, numpy, pandas, polars, pyarrow, h5py, zarr, xarray) | pyyaml 38, numpy 31, others 2–4 | nearly all `*`; zarr `>=3.1.6,<3.4`; numpy floors only | PyPI | — |

`requires-python`: `>=3.10` 6, `>=3.11` 35, `>=3.12` 8, `>=3.11,<3.13` 1 (spatio-flux).

### What forces version splits

1. **The process-bigraph floor vs pbest's pin.** `registry_env` runs process-bigraph **1.0.5**, pinned exactly by pbest
   0.6.3 (`process-bigraph==1.0.5`, `bigraph-schema==1.0.14` in its metadata). Every current middleware package needs
   ≥ 1.4.12 (emitters, basic-processes), ≥ 1.8.2 (superpowers) or ≥ 1.8.4 (workbench). None can join `registry_env`,
   nor can the 10 wrappers at `>=1.8.5`. This is the main split, and pbest's exact pin causes it, not the wrappers.
   Meanwhile 11 wrappers declare `>=0.0.10` with no ceiling: the solver picks the newest, so their compatibility with
   1.9 is asserted, not known.
2. **Aliases from the rename.** On PyPI harmless: `pbg-superpowers` 0.23.0 is a shim requiring `viva-superpowers`. On
   git not: five repos source `pbg-superpowers.git@main`, which redirects to a repo whose metadata says
   `viva-superpowers`; uv likely refuses the name mismatch *(unverified)*. `pbg-basic-processes` (PyPI) and
   `viva-basic-processes` (git only) are two distribution names for one module tree; an island pulling both could hold
   two copies or conflict (cf. [ModuleGuard](https://arxiv.org/abs/2401.02090)).
3. **URL-form conflicts.** viva-superpowers declares viva-basic-processes as a `[tool.uv.sources]` branch; the
   workbench declares it as a PEP 508 `git+…@main`; viva-simbio's comment says "uv treats those two forms as conflicting
   URLs" and it needs `override-dependencies` (`viva-simbio/pyproject.toml:60-69`); viva-biomodels works around it with
   a root source (`:72-81`). Every island holding both superpowers and workbench needs that override, and pixi does
   not read transitive uv sources at all.
4. **git `main` drift.** 15+ repos take superpowers and workbench from `main`; two islands locked on different days get
   different commits under one name. Only a lock or SHA pin makes them comparable; only viva-pde-particle pins SHAs.
5. **The workbench as a runtime dependency.** vivarium-workbench 0.4.1 requires viva-basic-processes, not on PyPI, so
   any island with the workbench needs git sources; its floors (zarr>=3.1.6, xarray>=2026.04, process-bigraph>=1.8.4)
   become constraints on every island holding it. 21 wrappers list it. Leaving it out is why viva-pde-particle's
   `compose` environment exists.
6. **Viz and data do not force splits today.** matplotlib, plotly, pandas and numpy are unpinned almost everywhere:
   good core candidates. Their versions still differ by island unless a solve-group fixes them, and numpy will follow
   what the COPASI, dolfinx and pyvcell-fvsolver builds need.

**Candidate core:** bigraph-schema, process-bigraph, viva-emitters, viva-basic-processes, bigraph-viz, pyyaml, numpy,
the viz libraries. Installable only at process-bigraph ≥ 1.8.x, so `registry_env` must move to the modern core before
it can share middleware with any other island. vivarium-workbench and viva-superpowers belong in a dev feature, not
in islands that run jobs. Prerequisites: publish viva-basic-processes to PyPI; one name per package (retire pbg-*
aliases); versioned releases instead of git `main`.

## Constraints

1. Feasibility is a joint solve per set, per platform; pairwise tests only filter.
2. Some items have no resolver at all (Rust builds, Node, Docker sidecars, a run-time compiler for AMICI, Python 2.7
   oxidizeme); they stay prebuilt-image islands outside the computed cover.
3. Only identical builds deduplicate; Apptainer SIFs share nothing without overlays or a bind-mounted store.
4. Identity, curation, addresses and placement must all become per island.
5. Island identity must be a digest (strategy decision 2), and images are write-once (E4), so the cover must be stable
   across recomputation.
6. The core cannot include `registry_env` until pbest's `process-bigraph==1.0.5` pin moves.

## Unknowns

- The real conflict sets among catalogue items: never computed. Whether the forest is two islands or ten.
- Demand: which composites people run, and their weights; no usage data is collected per composite.
- Whether the greedy cover is close to optimal at our scale, versus an exact ILP/ASP.
- How to extract minimal conflict sets from uv/pixi errors reliably (message parsing vs a library API).
- Whether uv refuses the `pbg-superpowers` git name mismatch.
- How placement chooses among islands that all host a replicated item (coupling research, Q1).
- Whether stacking overlays on our Apptainer makes a shared-core layout practical.
- Who owns the wire schema at an island boundary, and whether bigraph-schema `serialize` is stable from 1.0.14 to 1.8.

## Sources

- https://github.com/spack/spack/blob/develop/lib/spack/spack/solver/asp.py
- https://github.com/spack/spack/blob/develop/lib/spack/spack/solver/when_possible.lp
- https://spack.readthedocs.io/en/latest/environments.html
- https://pixi.prefix.dev/latest/workspace/multi_environment/
- https://prefix.dev/blog/pixi_a_fast_conda_alternative
- https://docs.astral.sh/uv/concepts/resolution/
- https://docs.astral.sh/uv/reference/settings/
- https://github.com/apptainer/apptainer/blob/main/CHANGELOG.md
- https://scitepress.org/PublishedPapers/2022/112632
- https://www.uncg.edu/cmp/faculty/srtate/pubs/buildenv
- https://www.irif.fr/~vouillon/coinst/
- https://2020.icse-conferences.org/details/icse-2020-papers/110/Watchman-Monitoring-Dependency-Conflicts-for-Python-Library-Ecosystem
- https://conf.researchr.org/details/ase-2022/ase-2022-research-papers/115/SmartPip-A-Smart-Approach-to-Resolving-Python-Dependency-Conflict-Issues
- https://conf.researchr.org/details/icse-2022/icse-2022-papers/90/Knowledge-Based-Environment-Dependency-Inference-for-Python-Programs
- https://arxiv.org/pdf/2201.07029
- https://arxiv.org/abs/2401.02090
- https://arxiv.org/pdf/2501.16191
- https://arxiv.org/pdf/2506.10803
- https://muscle3.readthedocs.io/en/latest/containers.html
- https://fmi-standard.org/docs/3.0
- https://avro.apache.org/docs/1.12.0/api/java/org/apache/avro/Resolver.html
- https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.md
- https://pypi.org/pypi/process-bigraph/json (and the same endpoint for each package in §8)
