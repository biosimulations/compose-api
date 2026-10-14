# Packaging and isolation tools

**Status (as of 2026-10-13): research, no decisions.** This chapter surveys the tools that could lock, build and ship
the environments ("islands") that compose-api runs composites in. Chapter 03 covers how to choose the islands.

**Verification.** A claim with a URL was read at that URL on 2026-10-13, by this chapter's author or by the research
pass it draws on. *(unverified)* marks a claim taken from memory or inference and not checked against a source.
Four load-bearing claims were re-checked for this chapter; their verdicts are in the table below and in the sections.

| | Claim | Verdict (2026-10-13) | Checked against |
|---|---|---|---|
| V1 | Spack `unify: when_possible` solves in rounds, maximising the roots solved per round | **Confirmed** | `solve_in_rounds` in [asp.py](https://github.com/spack/spack/blob/develop/lib/spack/spack/solver/asp.py); [when_possible.lp](https://github.com/spack/spack/blob/develop/lib/spack/spack/solver/when_possible.lp) |
| V2 | OCI-SIF and `--oci` mode belong to SingularityCE, not Apptainer | **Confirmed**, with a date correction: experimental `--oci` in SingularityCE 3.11, OCI-SIF in 4.0 | [SingularityCE CHANGELOG](https://github.com/sylabs/singularity/blob/main/CHANGELOG.md), [Sylabs OCI docs](https://docs.sylabs.io/guides/main/user-guide/oci_runtime.html), [Apptainer CHANGELOG](https://github.com/apptainer/apptainer/blob/main/CHANGELOG.md) |
| V3 | pixi `[target.<platform>]` does not support `pypi-dependencies` | **Corrected: it does.** The manifest JSON schema allows it; the prose reference omits it | [schema.json](https://github.com/prefix-dev/pixi/blob/main/schema/schema.json) (`$defs.Target.properties`), [manifest reference](https://pixi.prefix.dev/latest/reference/pixi_manifest/) |
| V4 | uv `tool.uv.conflicts` forks the resolution | **Confirmed** | [uv settings](https://docs.astral.sh/uv/reference/settings/) ("resolved in different forks"), [uv resolution](https://docs.astral.sh/uv/concepts/resolution/) |

## 1. pixi in depth

pixi is a project-level package manager from prefix.dev, written in Rust on the rattler libraries. It solves conda
packages with **resolvo**, a lazy CDCL SAT solver, and PyPI packages with **uv linked as a library**
([prefix.dev blog](https://prefix.dev/blog/pixi_a_fast_conda_alternative),
[conda + PyPI](https://pixi.prefix.dev/latest/concepts/conda_pypi/)). That makes it the one tool here that is both a
conda environment manager and a Python build front end, on every desktop OS. The sections below are what matters
for islands.

### 1.1 Features, environments and solve-groups

Source: [multi-environment](https://pixi.prefix.dev/latest/workspace/multi_environment/),
[manifest reference](https://pixi.prefix.dev/latest/reference/pixi_manifest/).

| Concept | What it is | Island reading |
|---|---|---|
| **Feature** | A named block: `dependencies`, `constraints`, `pypi-dependencies`, `pypi-options`, `system-requirements`, `activation`, `platforms`, `channels`, `channel-priority`, `solve-strategy`, `target`, `tasks` | A component or component group; the common middleware is one feature |
| **Environment** | A list of features; the default feature is included unless `no-default-feature = true` | An island |
| **`solve-group`** | "used to group environments together at the solve stage"; grouped environments get identical versions of the packages they share, each installs only its own subset | Islands that must agree on shared items |
| Environment outside a group | Solved alone; may diverge on any shared package | An island allowed to skew |

```toml
[feature.core.dependencies]        # common middleware, included by every island
python = "3.12.*"
[feature.core.pypi-dependencies]
process-bigraph = ">=1.8.5"
[feature.fenics.dependencies]
fenics-dolfinx = "0.10.*"
[feature.copasi.pypi-dependencies]
python-copasi = "*"

[environments]
pde    = { features = ["core", "fenics"], solve-group = "modern" }
kinetic = { features = ["core", "copasi"], solve-group = "modern" }
```

Illustrative only; package versions are not tested together. With both islands in `modern`, `process-bigraph` and
`numpy` resolve to one version in each; dropping `kinetic`'s `solve-group` lets it diverge.

**Precedent.** viva-pde-particle's `pixi.toml` (lines 98-114) has features `dev` and `workbench` and three
environments: `default` (the workbench), `compose` in the **same solve-group** as `default`, so the compose-api image
has `default`'s versions without the web app, and `dev`. `compose` exists because process-bigraph's discovery imports
every package that depends on bigraph-schema, and the workbench drags in more.

### 1.2 One lock across platforms

- `pixi.lock` holds **every environment for every platform** listed in `workspace.platforms`. Each package entry lists
  the environments that use it, so a shared package appears once
  ([multi-environment](https://pixi.prefix.dev/latest/workspace/multi_environment/)).
- Installs hard-link (or reflink) from a global package cache, so a shared package is downloaded once
  *(unverified for pixi's exact link modes; standard for conda)*.
- A content hash of one environment's section of the lock is a usable island identity before any image exists
  (inference).
- Lock time grows with environments × platforms (inference; not measured).

### 1.3 conda first, then PyPI

Source: [conda + PyPI](https://pixi.prefix.dev/latest/concepts/conda_pypi/).

1. resolvo solves the conda dependencies.
2. uv then solves the PyPI dependencies against the conda result, with PubGrub. The docs say a single solver for
   both ecosystems is "not yet implemented".
3. **`python` must be a conda dependency** for the PyPI solve to run.

**Name mapping (parselmouth).** pixi maps conda names to PyPI names with prefix.dev's parselmouth mapping, served from
`conda-mapping.prefix.dev`. `conda-pypi-map` entries are layered on the default; guessing that a conda name equals its
PyPI name is on by default only for conda-forge; offline, use `mapping-mode = "replace"` with a local file.

**Shadowing.** A package that arrives both ways is installed from conda; the PyPI requirement is ignored. A version
the conda solve already fixed can then make the PyPI solve fail (the docs' `typing_extensions` example). The fix is a
`[constraints]` entry, which "lets you restrict the versions of conda packages" and applies only when the package is
present ([manifest reference](https://pixi.prefix.dev/latest/reference/pixi_manifest/)), so the conda side honours the
PyPI bound.

**Sources.** PyPI dependencies may come from git (https or ssh), a path, or a URL (wheel or sdist); for path
dependencies the docs "highly recommend" `editable = true`. pixi does **not** read the `[tool.uv.sources]` of a
dependency, so git sources declared inside a wrapper's own `pyproject.toml` must be mirrored by hand in the island's
manifest. viva-pde-particle does exactly this for the workbench (`pixi.toml:75-76`).

### 1.4 `pypi-options`

Per feature or workspace ([manifest reference](https://pixi.prefix.dev/latest/reference/pixi_manifest/)):

| Option | Use for us |
|---|---|
| `index-url`, `extra-index-urls`, `index-strategy` | one index per environment; a private index for unpublished wrappers |
| `find-links` | a local wheelhouse (e.g. source-built Smoldyn) |
| `no-build-isolation` | build an sdist against the environment's conda toolchain (compilers, MPI) |
| `no-build` | refuse sdists, so no arbitrary code runs at resolve time |
| `no-binary` | force a source build of a package |
| `prerelease-mode`, `skip-wheel-filename-check` | edge cases |

### 1.5 Platform targets (V3)

`[target.<platform>]` overrides per platform. The prose reference says "the target table is currently implemented for
the following sub-tables": `activation`, `dependencies`, `constraints`, `tasks`. The manifest JSON schema on pixi
`main` ([schema.json](https://github.com/prefix-dev/pixi/blob/main/schema/schema.json), `$defs.Target`) lists
`activation`, `build-dependencies`, `constraints`, `dependencies`, `dev`, `host-dependencies`, **`pypi-dependencies`**
and `tasks`, described as "The PyPI dependencies for this target". **Verdict: per-platform PyPI dependencies are
expressible** (`[target.osx-arm64.pypi-dependencies]`, also inside a feature). The earlier research note that said
otherwise read only the prose list. Not exercised in a real lock here.

`system-requirements` is deprecated in favour of declaring virtual packages on `workspace.platforms`
([manifest reference](https://pixi.prefix.dev/latest/reference/pixi_manifest/)).

### 1.6 `pyproject.toml` as the manifest

Every pixi table can live under `[tool.pixi.*]`
([pyproject manifest](https://pixi.prefix.dev/latest/python/pyproject_toml/)):

| pyproject.toml | becomes in pixi |
|---|---|
| `project.dependencies` | PyPI dependencies of the default feature |
| `requires-python` | the `python` conda dependency |
| each `[project.optional-dependencies]` group | a feature of the same name |
| each `[dependency-groups]` group | a feature of the same name |
| `[build-system]` | used when the project is a PyPI path dependency; setuptools if absent |

- `pixi init` on an existing project makes one environment per feature, all in one solve-group, and adds the project
  itself as an editable PyPI dependency.
- A wrapper stays a normal package for pip and uv users, and pixi adds the conda layer (dolfinx, PETSc, compilers)
  under `[tool.pixi.dependencies]`.
- **Hazard.** A dependency declared in `project.dependencies` *and* as conda is taken from conda, silently (§1.3). pip
  and uv users then run the PyPI build of something pixi users get from conda: two populations, two binaries.

### 1.7 pixi-build (preview), source dependencies, `pixi publish`

Source: [pixi-build getting started](https://pixi.prefix.dev/latest/build/getting_started/).

- **Preview.** Enabled with `preview = ["pixi-build"]` under `[workspace]`; the docs list limitations.
- **Manifest.** `[package]` (name, version); `[package.build.backend]` (backend name and version) with
  `package.build.channels`; `[package.host-dependencies]` (build time, e.g. hatchling);
  `[package.run-dependencies]`.
- **Backends** with docs pages: Python (`pixi-build-python`), CMake, rattler-build, Rust, ROS, R, Mojo.
- **Source dependencies.** A `path`, `git` or `url` entry under `[dependencies]` makes `pixi install` / `pixi run`
  build that package **as a conda package** first.
- **`pixi publish`** builds a `.conda` file and uploads it to a channel or copies it to a directory.
- **Recipes.** The backends generate rattler-build recipes internally *(unverified)*; conda-forge accepts v1
  `recipe.yaml` recipes built with rattler-build *(unverified)*. So pixi-build → conda-forge is possible in principle,
  not one command. [rattler-build](https://github.com/prefix-dev/rattler-build) is the standalone builder.
- **What it would give us.** Rust/maturin wrappers (viva-cpm, viva-biofilm) and CMake builds (Smoldyn from source)
  become ordinary conda packages in a channel we own, consumed as conda dependencies, instead of sdists built at
  install time.

### 1.8 Python flavours and ABI hazards *(unverified throughout; general knowledge)*

- **Two CPython lines.** conda-forge's CPython links conda's own libraries. uv-managed CPython is
  python-build-standalone, a relocatable, mostly static build. pixi uses conda-forge's.
- **Wheels in conda Python** install fine when glibc is at least the wheel's manylinux tag. The real hazard is
  **duplicate native libraries**: a wheel vendors its own OpenBLAS, libstdc++, HDF5 or MPI next to conda's copies.
- **MPI is the sharpest case:** mpi4py, petsc4py or a pyvcell-fvsolver wheel against the conda mpich that dolfinx
  uses. On HPC, conda-forge's `external` MPI builds let the cluster's MPI stand in.
- **Rule:** anything that links MPI, PETSc, HDF5 or BLAS comes from conda; only pure-Python or self-contained wheels
  come from PyPI. pixi's conda-first shadowing (§1.3) enforces this when the package exists on conda.
- **Today's islands** run Python 3.12.15 (`registry_env`, uv image) and 3.12.13 (viva-pde-particle, conda-forge)
  (`compose_api/registry/manifests/*.json`). Both are 3.12, so cp312 wheels are portable between them.

### 1.9 Free-threaded builds

- pixi's Python tutorial documents `python-freethreading = "*"` as the way to get a free-threaded (PEP 703)
  interpreter from conda-forge ([pixi Python tutorial](https://pixi.prefix.dev/dev/python/tutorial/)).
- Almost none of our native dependencies (COPASI, roadrunner, dolfinx) are known to ship free-threaded builds
  *(unverified per package)*. Not relevant for islands now; possibly relevant later for in-island parallelism.

### 1.10 Shipping

**pixi-pack** ([Quantco/pixi-pack](https://github.com/Quantco/pixi-pack)):
- packs one environment from the lockfile into a `.tar` with a local channel and an `environment.yml`;
  `pixi-unpack` restores it;
- `--create-executable` makes a self-extracting `.sh` or `.ps1`;
- cross-packs (a win-64 pack built on linux-64);
- includes PyPI packages **as wheels only**; sdists need `--ignore-pypi-non-wheel` to be skipped;
- works from the lock, which is its edge over conda-pack. The README does not mention OCI images.

**The shell-hook OCI pattern** ([pixi container docs](https://pixi.prefix.dev/latest/deployment/container/)):
1. build stage `FROM ghcr.io/prefix-dev/pixi:<ver>`, `RUN pixi install --locked -e prod`;
2. `RUN pixi shell-hook -e prod -s bash > /shell-hook`, then an `entrypoint.sh` = hook + `exec "$@"`;
3. production stage from plain `ubuntu:24.04`, copying only `/app/.pixi/envs/prod` (the path must stay the same);
4. `ENTRYPOINT ["/app/entrypoint.sh"]`.

**Precedent.** viva-pde-particle ships this way: `docker/compose.Dockerfile` builds the `compose` environment, and
compose-api enters the image through `/app/docker/shell-hook.sh` (`compose_api/registry/environments.yaml:26-29`). It
is the only locked, SHA-pinned environment in the vivarium-collective org (conda-forge; `osx-arm64`, `linux-64`;
`python 3.12.*`, `fenics-dolfinx 0.10.*`; Smoldyn from a submodule; process-bigraph pinned to a revision). One image
per pixi environment means one SIF per island.

`pixi global` (pipx-like) and `pixi exec` (uvx-like) suit developer tooling, not islands *(unverified detail)*.

### 1.11 What breaks on Windows

| Problem | Effect |
|---|---|
| Apptainer has no Windows build | HPC parity needs WSL2 |
| Docker-sidecar wrappers (Chaste, tstmd) | need Docker Desktop or Podman |
| conda-forge win-64 gaps | `fenics-dolfinx` 0.11.0 **is** on win-64 (§3); cc3d is on its own channel for win-64 but the wrapper's `pixi.toml` lists only osx-arm64; readdy unchecked |
| Source builds (Smoldyn, Rust/CMake wrappers) | need MSVC toolchains |
| Filesystem | cache hardlinks/reflinks, long paths, `.bat`/`.ps1` activation *(unverified specifics)* |

Per-platform PyPI dependencies are not a blocker (V3). Expect Windows islands to be a subset of the full set.

### 1.12 pixi vs uv plus a conda base image

| | pixi | uv + conda/micromamba base image |
|---|---|---|
| Lock | one `pixi.lock`: conda + PyPI, every environment × platform | `uv.lock` (PyPI, universal) + a separately pinned base (Dockerfile or micromamba file) uv cannot see |
| Native libs (MPI, PETSc, BLAS) | conda-first shadowing keeps them consistent | ABI clashes between base and wheels found only at run time |
| Overlapping islands | features + solve-groups map directly | workspace members / extras + `tool.uv.conflicts`, PyPI only |
| Laptops | same environment natively on macOS and Linux, mostly Windows | base image needs a container runtime; not native |
| Git sources | must mirror transitive `[tool.uv.sources]` by hand | native, and what 38 of 50 catalogue pyprojects use |
| Speed | two solvers in sequence; conda side can block PyPI side | fastest PyPI path |
| Build system | pixi-build is preview | mature PEP 517 front end |
| Precedent | viva-pde-particle (island + image) | `registry_env` (pbest: uv base, micromamba line per conda package, no joint solve) |

## 2. uv

Source: [resolution](https://docs.astral.sh/uv/concepts/resolution/),
[settings](https://docs.astral.sh/uv/reference/settings/),
[project config](https://docs.astral.sh/uv/concepts/projects/config/).

- **Universal lock.** `uv.lock` covers all platforms and Python versions; "a package may be listed multiple times
  with different versions or URLs" and "the markers determine which version will be used". `--fork-strategy` trades
  fewer versions against newest-per-platform.
- **`tool.uv.environments`** narrows the platforms solved (entries "must be disjoint"); **`required-environments`**
  requires a wheel for each listed platform, failing the resolution otherwise.
- **`tool.uv.conflicts` (V4).** Declares extras or dependency groups "conflicting (i.e., mutually exclusive)". By
  default uv "resolves all project dependencies together, including optional dependencies ... and dependency groups"
  and fails on a conflict. With the declaration, uv "will resolve them separately"; the settings reference says the
  listed items are "resolved in different forks so that they cannot conflict with one another". At install, "you
  cannot install both `extra1` and `extra2` at the same time", since that "would result in installing two different
  versions of a package into the same environment". **Verdict: confirmed, it forks.** One lock can carry several
  mutually incompatible PyPI islands.
- **Workspaces** share one lock across members; with conflicts, a member or extra per island is the uv analogue of a
  pixi solve-group set.
- **Hard limit: one version per interpreter.** One interpreter has one `site-packages`, so one version of each
  distribution, and a module name is importable once ([ModuleGuard](https://arxiv.org/abs/2401.02090) studies module
  clashes). Two incompatible components cannot share a process; isolation must be at the process level.
- **No non-Python packages** (MPI, VTK, Java for VCell, Node for Artistoo).
- **Link modes.** `clone` (copy-on-write) by default on macOS and Linux, `hardlink` on Windows; `symlink` is warned
  against; across filesystems it falls back to a copy ([settings](https://docs.astral.sh/uv/reference/settings/)).

## 3. conda / mamba

- **Solvers.** conda and mamba use **libsolv** (SAT); pixi and rattler use **resolvo**
  ([prefix.dev blog](https://prefix.dev/blog/pixi_a_fast_conda_alternative)). conda's default solver is libmamba,
  i.e. libsolv *(unverified detail)*.
- **Locks.** [conda-lock](https://github.com/conda/conda-lock) is the older multi-platform lock; pixi's lock supersedes
  it for projects that use pixi.
- **One version per environment**, like uv.
- **The only ecosystem shipping compiled scientific stacks (MPI, PETSc) for Linux, macOS and Windows natively.**

**Coverage of our simulators** (anaconda.org API, checked 2026-10-13 by the research pass):

| Package | Where | Platforms |
|---|---|---|
| `fenics-dolfinx` 0.11.0 | conda-forge | linux-64, linux-aarch64, osx-64, osx-arm64, **win-64** |
| `python-libsbml` | conda-forge | all five |
| `readdy` 2.0.13 | conda-forge (used by `registry_env`) | platforms not checked |
| `cc3d` 4.10 (CompuCell3D) | its own `compucell3d` channel | linux-64, osx-64, osx-arm64, win-64 |
| `tissue-forge` | its own `tissue-forge` channel | linux-64, osx-64, osx-arm64, win-64 |
| `python-copasi`, `basico`, `smoldyn`, `tellurium`, `libroadrunner`, `physicell`, `pyvcell`, `process-bigraph` | **not on conda-forge** | PyPI wheels or source only |

- On Apple silicon dolfinx must be the native osx-arm64 build; osx-64 under Rosetta fails on AVX
  ([FEniCS discourse](https://fenicsproject.discourse.group/t/installing-fenics-on-windows-ck/14574)).
- The gap (COPASI, smoldyn, roadrunner) could be closed with rattler-build recipes on conda-forge or our own channel.

## 4. Spack

Source: [environments](https://spack.readthedocs.io/en/latest/environments.html),
[containers](https://spack.readthedocs.io/en/v1.1.1/containers.html),
[CHANGELOG](https://github.com/spack/spack/blob/develop/CHANGELOG.md).

A source-first HPC package manager. clingo (answer-set programming) concretizes; one install tree is keyed by a hash
of each spec's full configuration; an environment is `spack.yaml` (roots) + `spack.lock` + one or more views. Spack 1.0
(July 2025) made compilers dependencies and stabilized the package API
([FOSDEM 2026](https://archive.fosdem.org/2026/schedule/event/DHUQAN-spack-one-zero-and-beyond/)).

**Unify modes.**

| `concretizer:unify` | Meaning (docs) |
|---|---|
| `true` (default) | "any package in the environment corresponds to a single concrete spec"; the docs warn it "can be overly strict" |
| `false` | each root concretized independently |
| `when_possible` | reuse across roots "is only maximized"; the docs' example has two hdf5 builds sharing one zlib |

**How `when_possible` works (V1, confirmed).** `when_possible.lp` gives clingo the choice `{ solve_literal(ID) }` for
each input spec, requires at least one (`1 { solve_literal(ID) : literal(ID) }`), and minimises at high priority
`"number of input specs not concretized"`, so each solve concretizes the **largest set of roots that fit together**.
`SpackSolver.solve_in_rounds` in `asp.py` (docstring: "Each round tries to maximize the reuse of specs from previous
rounds") loops: solve, yield the round, stop if nothing is unsolved, **raise** `OutputDoesNotSatisfyInputError` if a
round solved nothing, else re-solve only the unsolved roots with every spec solved so far added to the reusable set.
The result is a greedy sequence of internally consistent groups; nothing guarantees the fewest groups. All rounds
land in **one** environment, which may then hold two versions of a package.

**Shared install tree and views.**
- "Spack maintains a single installation of the software that can be re-used across multiple environments": any number
  of environments are views over one hash-addressed store, so identical builds exist once.
- Views: symlink by default, or `hardlink`/`copy`; `select`/`exclude`, `projections`, and `link: roots|run|all`.
  A `unify: false` environment holding two versions collides in a single view unless projections separate them.
- **`include_concrete`** composes an environment from other environments' locks, without re-solving them.

**Containers and caches.**
- `spack containerize` emits a multi-stage Dockerfile or Singularity definition from `spack.yaml`.
- `spack buildcache push` to an `oci://` mirror (since 0.21) publishes a binary cache that is also a runnable image;
  one layer per package, so images share layers *(unverified: the per-package layering)*.

**Platforms.** Linux/HPC first-class; macOS arm64 works but is less exercised; Windows native but narrow: "MSVC is the
only compiler tested", path-length limits, no package list
([Windows docs](https://spack.readthedocs.io/en/latest/windows.html),
[Kitware](https://kitware.com/spack-on-windows-a-new-era-in-cross-platform-dependency-management)).

**Python coverage.** `py-*` recipes cover far less than PyPI; most of our simulators would need new recipes. Without a
binary cache everything builds from source. An expert tool, not a laptop one.

## 5. Nix / Guix

- **Model.** Purely functional stores (`/nix/store/<hash>-name`): any number of versions coexist by construction, many
  builds are bit-for-bit reproducible.
- **Guix** adds `guix time-machine` and `guix pack -f squashfs`, an image Apptainer can run
  ([Grid'5000](https://grid5000.fr/w/Guix)); production cluster deployments exist (MDC, Inria PlaFRIM;
  [Courtès](https://miat.inrae.fr/site/images/2/2d/Seminaire_ludovic_courtes.pdf)).
- **Platforms.** Nix: Linux, macOS (no "full feature parity";
  [rix vignette](https://docs.ropensci.org/rix/articles/setting-up-macos.html)), Windows only via WSL2. Guix: Linux
  only. On HPC the store needs a daemon or root at `/nix` unless packs or containers are shipped.
- **Pitfalls.** Steep learning curve; nixpkgs Python science packages lag PyPI and break often *(unverified as a
  current measurement)*; the Python layer's reproducibility still rests on wheels or overrides.
- **Fit.** An image builder, not a user-facing tool.

## 6. Containers

### 6.1 OCI images

- Images are content-addressed layers; a layer is shared, in the registry and in the pull cache, only if its bytes
  match. Dockerfile layers stack in order, so shared components must sit in a common base or common prefix of layers.
- Pin by `@sha256:` digest, never by tag. compose-api pins `viva-pde-particle` by digest
  (`kustomize/config/compose-api-rke/api.env:4`); `registry_env`'s identity is still the md5 of a definition whose base
  is a mutable tag (`FROM astral/uv:python3.12-bookworm-slim`).
- **ORAS** (`oras://`) stores arbitrary artifacts (SIF files, locks) in the same registry.
- **Multi-arch:** `docker buildx --platform linux/amd64,linux/arm64` makes one manifest index.

### 6.2 Apptainer

Source: [Apptainer CHANGELOG](https://github.com/apptainer/apptainer/blob/main/CHANGELOG.md). Latest release
**1.5.4 (2026-09-22)**; 1.6.x is unreleased (an undated "Changes since 1.5.x" section). compose-api's k8s builder runs
`ghcr.io/apptainer/apptainer:1.3.6` (`docs/plan-environment-builds.md`, phase 3).

- **SIF** is one squashfs file; two SIFs share nothing on disk.
- **Persistent overlays:** ext3 overlay images (work without root), `:ro` mounts, an overlay embedded as a SIF
  partition (`apptainer sif add`); not addable to a signed SIF
  ([persistent overlays](https://apptainer.org/docs/user/latest/persistent_overlays.html)). Stacking several
  read-only squashfs overlays *(unverified)*.
- **1.4:** `--arch` / `--arch-variant` builds for another architecture (needs binfmt_misc); multi-arch oci-archive
  with a nested index; oras beyond amd64.
- **1.6 (unreleased) `build --overlay`:** "produces an image containing only the files added, changed, or removed
  relative to a `Bootstrap: localimage` base image. A hash of the base image is included in the metadata"; default
  output is a SIF with an overlay partition, `--sandbox` gives a sandbox; the base cannot be a sandbox. A real
  per-island layering primitive on top of a shared base SIF.
- **1.6 (unreleased):** multi-arch push to an `oras://` URI creating an image index; data partitions from tar files;
  archive mounts via FUSE.
- **No OCI-SIF, no `--oci` runtime mode** anywhere in the Apptainer changelog (V2).

### 6.3 SingularityCE: OCI mode and OCI-SIF (V2)

Source: [SingularityCE CHANGELOG](https://github.com/sylabs/singularity/blob/main/CHANGELOG.md),
[Sylabs OCI docs](https://docs.sylabs.io/guides/main/user-guide/oci_runtime.html).

| Version | Change |
|---|---|
| 3.11.0 (2023-02-10) | experimental `--oci` for `run/exec/shell`: OCI bundle via `runc` or `crun`; OCI sources only, "does not support running Singularity SIF, SquashFS, or EXT3 images" |
| 4.0.0 (2023-09-19) | OCI-SIF: `pull --oci` makes an OCI-SIF; push/pull as single-file `oras://` artifacts or as single-squashfs-layer `docker://` images; `oci mode` config directive. The docs: OCI-SIF files "are only supported by SingularityCE 4.0 and above" |
| 4.2.0 (2024-09-04) | `overlay create` adds a writable ext3 overlay to an OCI-SIF (read-only unless `--writable`); `overlay seal` converts it to a read-only squashfs layer; `--layer-format tar` pushes layers other OCI runtimes can run; `data package` |
| **4.6.0 (2026-10-05)** | "expected to be the final release managed by Sylabs ... security, bugfix, and feature development will no longer be performed by Sylabs" |

So OCI-SIF is a SingularityCE 4.x feature, and **SingularityCE itself reached end of Sylabs maintenance on
2026-10-05**. The cluster runs `singularity build --fakeroot` (CLAUDE.md); whether its `singularity` is Apptainer's
compatibility command or SingularityCE is not recorded here (Unknowns).

### 6.4 Rootless builds

Source: [Apptainer fakeroot](https://apptainer.org/docs/user/1.4/fakeroot.html),
[admin user namespaces](https://apptainer.org/docs/admin/1.5/user_namespace.html).
- Preferred: `/etc/subuid` / `/etc/subgid` mappings (`apptainer config fakeroot` since 1.3); fallbacks are a
  root-mapped user namespace, then the `fakeroot` binary.
- Ubuntu 24.04+ restricts unprivileged user namespaces through AppArmor; kernel ≥ 5.11 is recommended for
  unprivileged overlayfs.
- Our cluster: `FATAL: could not use fakeroot: no mapping entry found in /etc/subuid for svc_compose`; builds moved
  to a privileged Kubernetes Job (`docs/plan-environment-builds.md`, decisions E6–E7).

### 6.5 Desktop runtimes

| Runtime | Platforms | Notes |
|---|---|---|
| Docker Desktop | macOS, Windows (WSL2) | paid subscription for larger companies ([pricing](https://www.docker.com/pricing/)) |
| Podman | Linux rootless; `podman machine` on macOS, Windows | |
| Colima / Lima | macOS | free VMs |
| Apple `container` | Apple silicon, macOS 26 | 1.0 June 2026, Apache-2.0, one lightweight VM per container, OCI-compatible, no Compose ([Help Net Security](https://www.helpnetsecurity.com/2026/07/07/apple-container-open-source-linux-mac/), [InfoQ](https://www.infoq.com/news/2025/06/apple-container-linux)) |

Macs need linux/arm64 image variants: amd64 under emulation is slow, and dolfinx fails under Rosetta (no AVX).

## 7. Prior art: per-step environments

**Galaxy / BioContainers** ([mulled](https://docs.galaxyproject.org/en/master/admin/special_topics/mulled_containers.html),
[container resolvers](https://docs.galaxyproject.org/en/master/admin/container_resolvers.html)).
- A tool declares `<requirement type="package" version=...>`. One package → a BioContainers image (`pkg:ver--build`);
  several → **mulled-v2**, named `mulled-v2-<hash of names>:<hash of versions>-<build>`. The name is a deterministic
  function of the requirement set (`mulled-hash samtools=1.3.1,bedtools=2.22`), so anyone can probe the registry
  before building.
- Resolution order: explicit container → cached mulled image → quay.io → on-demand build (involucro + conda).
- Singularity copies at [depot.galaxyproject.org/singularity](https://depot.galaxyproject.org/singularity/), also on
  CVMFS. Granularity: the tool.

**Snakemake** ([deployment](https://snakemake.readthedocs.io/en/v5.32.0/snakefiles/deployment.html)).
Per-rule `conda:` and/or `container:`; an environment is cached under a hash of the env file plus the container URL;
`snakemake --containerize` writes one Dockerfile holding all rule environments. Parallel jobs race creating the same
environment ([phables](https://phables.readthedocs.io/en/latest/container/)).

**Nextflow / Wave / Seqera Containers** ([Wave](https://docs.seqera.io/nextflow/wave),
[Seqera Containers](https://docs.seqera.io/wave/seqera-containers)).
Per-process `conda`/`container`. Wave builds on demand from a conda list, `environment.yml`, a Dockerfile or Spack, on a
micromamba base, and can emit Singularity images as ORAS artifacts. Seqera Containers (`community.wave.seqera.io`):
"the same hash returns the same image for at least five years"; linux/amd64 and arm64, never macOS.

**CWL / WDL.** CWL `DockerRequirement` (`dockerPull`, digest) or `SoftwareRequirement` (packages, versions,
specs/RRIDs), which cwltool resolves through Galaxy's resolvers (conda, modules, mulled)
([cwltool](https://dyn.manpages.debian.org/unstable/cwltool/cwltool.1.en.html)). WDL: per-task `runtime { docker }`.

**The common pattern.**
1. Granularity follows the declared unit (tool, rule, process, task).
2. The cache key is a canonical hash of the normalised requirement set.
3. A registry probe precedes any build; builds are on demand and then cached.
4. **None merges steps into fewer environments.** Galaxy merges only what one tool lists. Choosing the islands
   (chapter 03) has no precedent in these systems.

## 8. Comparison

| | Several versions in one env | Shared store across envs | Lock | Non-Python libs | HPC | Linux | macOS arm64 | Windows | Our simulators | Maturity |
|---|---|---|---|---|---|---|---|---|---|---|
| pixi | No (solve-groups across envs) | Package cache, links | one, all envs × platforms | Yes (conda) | Good | Good | Good | Good, gaps (§1.11) | dolfinx, libsbml, readdy; PyPI for the rest | High; pixi-build preview |
| conda/mamba | No | Package cache, links | conda-lock | Yes | Good | Good | Good | Good | as pixi | High |
| uv | No (process isolation) | Cache, clone/hardlink | universal, conflict forks | No | Good | Good | Good | Good | PyPI wheels: most | High |
| Spack | `unify:false`/`when_possible` (view collisions) | Hash store + views | `spack.lock` per env | Yes (source) | Excellent | Good | Fair | Narrow (MSVC) | Low for Python sims | High (1.x) |
| Nix/Guix | Yes (store) | Yes | flake / channels | Yes | Fair (packs) | Excellent | Nix fair, Guix none | WSL only | Low | Medium |
| OCI images | Per image | Layers, by digest | n/a (digest) | Anything | via Apptainer | Excellent | via VM, arm64 images | via WSL2 | whatever is built | High |
| Apptainer SIF | Per image | None; overlays (1.6 `build --overlay`) | n/a (sha256) | Anything | Excellent | Excellent | No | No | whatever is built | High |
| Galaxy mulled / Wave | Per image | Registry cache by hash | requirement hash | conda | Yes (Singularity) | Yes | images only | images only | conda/PyPI | High |

## Constraints

1. One interpreter holds one version of each distribution (uv, pip, conda, pixi alike); incompatible components need
   separate processes, hence separate islands.
2. Several of our engines are not on conda-forge (COPASI, smoldyn, tellurium/roadrunner, VCell, PhysiCell,
   process-bigraph) and several are not on PyPI as wheels (Smoldyn usable build, Rust wrappers, Node, Docker
   sidecars). No single package ecosystem covers the forest.
3. Native libraries (MPI, PETSc, HDF5, BLAS) must come from one source per island; conda-first is the only rule that
   holds on all three desktop OSes.
4. pixi does not read transitive `[tool.uv.sources]`; 38 of 50 catalogue pyprojects use git sources, nearly all
   `branch=main`.
5. SIFs share nothing on disk; sharing on HPC needs overlays or a bind-mounted store.
6. The cluster cannot build with fakeroot; builds run in a privileged Kubernetes Job.
7. Image identity must be a digest, not the md5 of a non-reproducible recipe (strategy decision 2, not implemented).
8. Apptainer has no OCI-SIF; SingularityCE has it but is out of Sylabs maintenance as of 2026-10-05.

## Unknowns

- Which `singularity` the cluster runs (Apptainer's compatibility command or SingularityCE), and its version.
- When Apptainer 1.6 (`build --overlay`, multi-arch oras) is released, and whether our build image can move to it.
- Whether several read-only squashfs/ext3 overlays stack on our Apptainer version.
- Hardlink and reflink behaviour of pixi and uv caches on the shared filesystem behind `<store>` (NFS/GPFS type
  unknown).
- Lock and solve time of a pixi workspace with ~10 islands × 3–5 platforms.
- Whether pixi-build leaves preview, and whether its backends' generated recipes are accepted by conda-forge.
- readdy's conda-forge platforms, and which wrappers ship free-threaded or osx-arm64 builds.
- Per-platform `pypi-dependencies` (V3) is in the schema but untested here.
- Spack's OCI build cache layering per package, not re-checked.

## Sources

- https://github.com/spack/spack/blob/develop/lib/spack/spack/solver/asp.py
- https://github.com/spack/spack/blob/develop/lib/spack/spack/solver/when_possible.lp
- https://github.com/spack/spack/blob/develop/CHANGELOG.md
- https://spack.readthedocs.io/en/latest/environments.html
- https://spack.readthedocs.io/en/v1.1.1/containers.html
- https://spack.readthedocs.io/en/latest/windows.html
- https://kitware.com/spack-on-windows-a-new-era-in-cross-platform-dependency-management
- https://archive.fosdem.org/2026/schedule/event/DHUQAN-spack-one-zero-and-beyond/
- https://github.com/apptainer/apptainer/blob/main/CHANGELOG.md
- https://apptainer.org/docs/user/latest/persistent_overlays.html
- https://apptainer.org/docs/user/1.4/fakeroot.html
- https://apptainer.org/docs/admin/1.5/user_namespace.html
- https://github.com/sylabs/singularity/blob/main/CHANGELOG.md
- https://docs.sylabs.io/guides/main/user-guide/oci_runtime.html
- https://prefix.dev/blog/pixi_a_fast_conda_alternative
- https://pixi.prefix.dev/latest/workspace/multi_environment/
- https://pixi.prefix.dev/latest/reference/pixi_manifest/
- https://github.com/prefix-dev/pixi/blob/main/schema/schema.json
- https://pixi.prefix.dev/latest/concepts/conda_pypi/
- https://pixi.prefix.dev/latest/python/pyproject_toml/
- https://pixi.prefix.dev/latest/build/getting_started/
- https://pixi.prefix.dev/latest/deployment/container/
- https://pixi.prefix.dev/dev/python/tutorial/
- https://github.com/Quantco/pixi-pack
- https://github.com/prefix-dev/rattler-build
- https://github.com/conda/conda-lock
- https://docs.astral.sh/uv/concepts/resolution/
- https://docs.astral.sh/uv/reference/settings/
- https://docs.astral.sh/uv/concepts/projects/config/
- https://arxiv.org/abs/2401.02090
- https://fenicsproject.discourse.group/t/installing-fenics-on-windows-ck/14574
- https://grid5000.fr/w/Guix
- https://miat.inrae.fr/site/images/2/2d/Seminaire_ludovic_courtes.pdf
- https://docs.ropensci.org/rix/articles/setting-up-macos.html
- https://www.docker.com/pricing/
- https://www.helpnetsecurity.com/2026/07/07/apple-container-open-source-linux-mac/
- https://www.infoq.com/news/2025/06/apple-container-linux
- https://docs.galaxyproject.org/en/master/admin/special_topics/mulled_containers.html
- https://docs.galaxyproject.org/en/master/admin/container_resolvers.html
- https://depot.galaxyproject.org/singularity/
- https://snakemake.readthedocs.io/en/v5.32.0/snakefiles/deployment.html
- https://phables.readthedocs.io/en/latest/container/
- https://docs.seqera.io/nextflow/wave
- https://docs.seqera.io/wave/seqera-containers
- https://dyn.manpages.debian.org/unstable/cwltool/cwltool.1.en.html
