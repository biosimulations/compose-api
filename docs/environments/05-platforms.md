# Platforms: HPC, Linux, macOS, Windows

**What this chapter covers.** Where each tool and each simulator family runs, natively or in a container, as of
2026-10-13. The decision this chapter supports is EV11 in [plan-environments-epoch2.md](../plan-environments-epoch2.md).

**How the facts were gathered.**
- **Package availability** was queried on 2026-10-13. conda packages came from the anaconda.org API
  (`api.anaconda.org/package/<channel>/<name>`). PyPI wheels came from the PyPI JSON API, using each package's
  latest release.
- **Two caveats on that data:**
  - anaconda.org's `conda_platforms` lists every platform any version was ever built for, not only the latest
    version.
  - A PyPI row describes the newest release only. An older release may cover a platform the newest one does not.
- **Tool support** was checked against upstream docs where a link is given.
- A claim marked *(unverified)* came from the research reports and was not re-checked here.

**The four platforms:**

| Platform | What it means here |
|---|---|
| **HPC** | Mantis: SLURM, Apptainer, x86_64, a shared filesystem. compose-api submits there over SSH. |
| **Linux** | A workstation or server, x86_64 or aarch64, with Docker or Podman and possibly Apptainer. |
| **macOS** | Apple silicon (`osx-arm64`). Intel Macs (`osx-64`) are legacy and not a target. |
| **Windows** | Windows 10/11 on x86_64 (`win-64`), with or without WSL2. |

---

## 1. Tools by platform

**N** = runs natively. **C** = only in a Linux container or VM. **—** = not supported.

| Tool | HPC | Linux | macOS arm64 | Windows | Notes |
|---|---|---|---|---|---|
| **pixi / conda** (conda-forge) | N | N | N | N | conda-forge builds for `linux-64`, `linux-aarch64`, `osx-64`, `osx-arm64` and `win-64`; package coverage differs per platform (§2) |
| **uv / pip** | N | N | N | N | Python only. A universal `uv.lock` forks on markers, so one file covers all platforms ([uv resolution](https://docs.astral.sh/uv/concepts/resolution/)). Wheels decide what actually installs |
| **Spack** | N (first-class) | N | N (less exercised) | N, narrow | Windows: "MSVC is the only compiler tested"; path-length limits ([Spack on Windows](https://spack.readthedocs.io/en/latest/windows.html)) |
| **Nix** | N with a daemon or packs | N | N, "does not have full feature parity" ([rix vignette](https://docs.ropensci.org/rix/articles/setting-up-macos.html)) | C (WSL2) | the store needs `/nix` or root on a cluster, unless you ship packs or containers |
| **Guix** | N (`guix pack -f squashfs` for Apptainer) | N | — | C (WSL2) | Linux only ([Grid'5000 Guix](https://grid5000.fr/w/Guix)) |
| **Docker** | — (no daemon for users) | N | C (Docker Desktop VM) | C (Docker Desktop, WSL2 backend) | Docker Desktop needs a paid subscription in larger companies ([pricing](https://www.docker.com/pricing/)) |
| **Podman** | possible, rootless *(unverified on Mantis)* | N, rootless | C (`podman machine`) | C (`podman machine`) | |
| **Apple `container`** | — | — | C, Apple silicon only | — | 1.0 shipped June 2026: Apache-2.0, one lightweight VM per container, OCI-compatible, no Compose, needs macOS 26 ([Help Net Security](https://www.helpnetsecurity.com/2026/07/07/apple-container-open-source-linux-mac/)) *(unverified here)* |
| **Apptainer** | N (the runtime we use) | N | C (Lima VM) | C (WSL2) | "Not possible to run on Windows or Mac because of basic incompatibilities with the host kernel"; the docs recommend WSL2 and Lima ([admin docs](https://github.com/apptainer/apptainer-admindocs/blob/main/installation.rst)) |
| **MPI** (Open MPI, MPICH) | N (the site's MPI) | N | N (conda-forge `mpich`, `openmpi`) | MS-MPI only (conda-forge `msmpi`, `win-64`) | conda-forge's `mpich`/`openmpi` have no `win-64` build |
| **Ray** | community SLURM support ([guide](https://gitea.com/qu-bit/ray/src/branch/master/doc/source/cluster/slurm.rst)) | N | N | **beta** | "Ray on Windows is currently in beta" ([install docs](https://github.com/ray-project/ray/blob/master/doc/source/ray-overview/installation.md)). Per-actor containers use Podman only and are experimental ([RuntimeEnv](https://docs.ray.io/en/latest/ray-core/api/doc/ray.runtime_env.RuntimeEnv.html)) |
| **MUSCLE3** | N (SLURM-native) | N | N | unknown | "Building libmuscle is currently supported on GNU/Linux and macOS" ([installing](https://github.com/multiscale/muscle3/blob/develop/docs/source/installing.rst.in)). The `muscle3` wheel is pure Python. Windows is not stated anywhere *(unverified)* |

**Container images by architecture.**
- **Multi-arch images.** `docker buildx --platform linux/amd64,linux/arm64` produces one manifest index. Wave and
  Seqera Containers build both architectures but never macOS ([Seqera Containers](https://docs.seqera.io/wave/seqera-containers)).
- **Apptainer.** It added cross-architecture builds (`--arch`, 1.4.0). Multi-arch `oras://` image indexes are in
  the unreleased 1.6.x section ([CHANGELOG](https://github.com/apptainer/apptainer/blob/main/CHANGELOG.md)).
- **Correction to `plan-container-runtimes.md:146`.** **OCI-SIF and the `--oci` mode belong to SingularityCE 4.x,
  not Apptainer.** Apptainer's CHANGELOG never mentions OCI-SIF (grep, 2026-10-13); the feature is SingularityCE's
  ([Sylabs OCI docs](https://docs.sylabs.io/guides/main/user-guide/oci_runtime.html)).

---

## 2. Simulator families by platform

`L` = `linux-64` / x86_64, `La` = `linux-aarch64`, `M` = `osx-arm64` / macOS arm64, `W` = `win-64` / win_amd64.

### What each source provides

| Item | conda (channel: platforms) | PyPI, newest release (wheel platforms) | Python tags |
|---|---|---|---|
| **python-copasi** (COPASI) | not on conda-forge | 4.48.309: L, La, M, W (+ macOS x86_64, win-arm64) | cp310–cp315 |
| **libroadrunner** | not on conda-forge | 2.10.0: L, M, W (**no La**) | cp311–cp314 |
| **tellurium** | not on conda-forge | 2.2.13.1: pure Python (needs libroadrunner) | py3 |
| **python-libsbml** | conda-forge: L, La, M, W | 5.21.2: L, La, M, W | cp310–cp315 |
| **smoldyn** | not on conda-forge | 2.75: **W only**; 2.74: L only; 2.73: L, macOS universal2, W. Stable wheels stop at **cp311** | ≤ cp311 |
| **readdy** | conda-forge 2.0.14: **L, osx-64 only** | 2.0.14: L, M (+ sdist) | cp310–cp313 |
| **fenics-dolfinx** (FEniCSx) | conda-forge 0.11.0: L, La, M, W (+ osx-64, ppc64le) | not on PyPI | — |
| **petsc** | conda-forge: L, La, M (**no W**) | — | — |
| **pyvcell** / **pyvcell-fvsolver** | not on conda-forge | pyvcell pure; fvsolver 0.11.1: L, La, M, W | fvsolver **cp312 only** |
| **pysces** | not on conda-forge | 1.2.3: L, M, W (+ win-arm64) | cp310–cp314 |
| **lammps** | conda-forge: L, La, M (**no W**) | 2025.7.22.4.0: L, La, M, W | py2.py3 |
| **amici** | not on conda-forge | 1.1.0: **sdist only**; compiles C++ per model | ≥ 3.12 |
| **ipopt** (ketchup) | conda-forge: L, La, M, W | — | — |
| **cobra** | conda-forge noarch | pure | — |
| **CompuCell3D** (`cc3d`) | `compucell3d` channel 4.10.0: L, M, W (+ osx-64) | not on PyPI | — |
| **Tissue Forge** | `tissue-forge` channel 0.2.1: L, M, W (+ osx-64) | not on PyPI | — |
| **Chaste** | `pychaste` channel: L, La, M (**no W**) | — | — |
| **PhysiCell** | not packaged | not on PyPI; source build with OpenMP | — |
| **process-bigraph**, **bigraph-schema** | not on conda-forge | pure (1.9.1, 1.8.1) | py3 |
| **pb-multiscale-actin** | — | 1.3.1: sdist only | — |
| **muscle3** | not on conda-forge | 0.10.0 pure (libmuscle C++ separate) | py3 |
| **mpi4py** | — | 4.1.2: L, La, M, W | cp38–cp314 |

### Where each family runs natively

Read off the table above. "Image" means only in a Linux container.

| Family (catalogue packaging, see [01 §5](01-current-state.md)) | HPC | Linux x86_64 | Linux aarch64 / arm64 images | macOS arm64 native | Windows native |
|---|---|---|---|---|---|
| ODE/SBML: COPASI, libsbml, pysces | yes | yes | yes | yes | yes |
| tellurium / libroadrunner | yes | yes | **no wheel** | yes | yes |
| readdy | yes | yes | **no** | PyPI wheel only (not conda) | **no** |
| Smoldyn | source build | old wheels ≤ cp311; source | source | source (viva-pde-particle builds it) | 2.75 wheel ≤ cp311 |
| FEniCSx / dolfinx (+PETSc, MPI) | yes (image) | yes | yes | yes (native `osx-arm64`) | dolfinx `win-64` exists; PETSc and MPICH do not *(whether dolfinx on `win-64` covers our use is unverified)* |
| VCell: pyvcell + fvsolver | yes | yes | yes | yes (wheel tagged macOS 15) | yes, cp312 only |
| CompuCell3D | via conda channel | yes | **no** | yes | yes |
| Chaste | via conda channel or Docker | yes | yes | yes | **no** (Docker/WSL2) |
| Rust / maturin (viva-cpm, viva-biofilm) | build | build | build | build | build with MSVC |
| Node, Java, Docker sidecars (Artistoo, comets, tstmd) | image | image or runtime | image | image or runtime | image or runtime |
| AMICI (compile per model) | yes, with a compiler | yes | yes | yes (Xcode clang) | MSVC *(unverified)* |
| PhysiCell (OpenMP C++) | source | source | source | needs an OpenMP g++ (`PHYSICELL_CPP`) ([releases](https://github.com/MathCancer/PhysiCell/releases)) | MinGW/MSYS2 *(unverified)* |

### Consequences for today's two islands

- **`registry_env` cannot be built for arm64 as written.** It installs readdy from conda-forge, which has no
  `linux-aarch64` or `osx-arm64` build, and libroadrunner has no `linux-aarch64` wheel. pbest's template also
  downloads `micromamba/linux-64/latest`. So no arm64 image exists or can be built for Macs. Native `osx-arm64`
  would need readdy from its PyPI wheel instead.
- **viva-pde-particle locks `osx-arm64` and `linux-64`.** Its compose image is built for linux/amd64 only. The
  workbench image from that repo builds `linux/amd64,linux/arm64` (`build-and-push.yml`, `IMAGE_PLATFORMS`).
- **Smoldyn has no stable cp312 wheel on any platform.** That is why viva-pde-particle builds it from source with
  conda compilers.

---

## 3. Platform notes

### HPC (Mantis)

- **Builds.** The service user cannot build with fakeroot on the build node: "no mapping entry found in /etc/subuid
  for svc_compose" (`kustomize/config/compose-api-rke/api.env:9-11`; `compose_api/simulation/build_k8s.py:4-6`).
  - Production therefore builds in a **privileged Kubernetes init container** with no shared storage mounted
    (`build_k8s.py:83-91,130-150`; `ghcr.io/apptainer/apptainer:1.3.6`, `api.env:14`). It copies the SIF onto the
    store as the service user.
  - The SLURM path, `singularity build --fakeroot` (`compose_api/simulation/simulation_service.py:189`), stays for
    sites that can build.
- **Rootless options** ([fakeroot docs](https://apptainer.org/docs/user/1.4/fakeroot.html), [user namespaces](https://apptainer.org/docs/admin/1.5/user_namespace.html)):
  - `/etc/subuid` mappings, which is the preferred mode;
  - a root-mapped user namespace;
  - the `fakeroot` binary.

  Kernel ≥ 5.11 is recommended for unprivileged overlayfs *(unverified for Mantis's kernel)*.
- **Running** needs no build privilege. `singularity run --compat <sif>` from the shared store. Pulls by digest
  (`docker://…@sha256:`) already work for prebuilt images (`api.env:4`).
- **Sharing on disk.**
  - Each SIF is one flattened squashfs, so islands share nothing on disk.
  - Apptainer 1.6.x (unreleased) adds `apptainer build --overlay`. It produces an image of only the files changed
    relative to a `Bootstrap: localimage` base and records the base's hash
    ([CHANGELOG](https://github.com/apptainer/apptainer/blob/main/CHANGELOG.md)).
  - Stacking several read-only overlays is untested here (experiment X2).
- **MPI.**
  - The preferred model is **hybrid**: the host's `mpirun`/`srun` launches `apptainer exec`, with an ABI-compatible
    MPI inside the image. The bind model mounts the host MPI and is less portable
    ([Apptainer MPI](https://apptainer.org/docs/user/1.5/mpi.html)).
  - conda-forge offers `external` MPI builds that defer to the host's MPI *(unverified detail)*.
  - `MPI_Comm_spawn` under SLURM is fragile: the PMIx plugin returns "not supported"
    ([SchedMD #9979](https://support.schedmd.com/show_bug.cgi?id=9979)). Pre-launch ranks instead.
- **Architecture.** x86_64. Both current images are linux/amd64.
- **Open questions** (`docs/plan-container-runtimes.md` §6, still unasked):
  - the Apptainer version on the nodes;
  - Enroot/Pyxis;
  - Apptainer OCI mode;
  - subuid for `svc_compose`.

### Linux

- **Everything runs here.** Native pixi/uv, Docker/Podman, and Apptainer if installed. It is the reference
  platform for tests.
- **Rootless containers.** Podman is rootless by default. Ubuntu 24.04+ restricts unprivileged user namespaces
  through AppArmor, which affects rootless Apptainer and Podman until a profile allows them *(unverified detail)*.
- **aarch64 gaps** (Graviton, Ampere, and arm64 images on Macs): libroadrunner, readdy and CompuCell3D have no
  aarch64 build (§2).
- **Shared caches.** The uv and pixi caches hardlink or clone into environments on the same filesystem. Across
  filesystems they copy.

### macOS (Apple silicon)

- **Native first.** conda-forge covers `osx-arm64` for FEniCSx, PETSc, MPICH/Open MPI, libsbml and ipopt.
  - PyPI covers COPASI, libroadrunner, pysces, pyvcell-fvsolver, readdy (wheel) and Ray.
  - viva-pde-particle already locks `osx-arm64` natively.
  - pyvcell-fvsolver wheels are tagged `macosx_15_0`, so pixi needs `macos = "15.0"` (viva-pde-particle
    `pixi.toml:26-28`).
- **Containers mean arm64 images.**
  - Rosetta translates x86_64 but does not execute AVX, AVX2 or AVX-512 instructions
    ([MongoDB SERVER-56728](https://jira.mongodb.com/browse/SERVER-56728), [docker/for-mac#6620](https://github.com/docker/for-mac/issues/6620)).
    So amd64 images whose numerics were built with AVX crash with an illegal instruction.
  - FEniCS failing that way is reported *(unverified: the research report's FEniCS discourse link does not discuss
    Rosetta or AVX)*.
  - Turning Rosetta off makes Docker use QEMU, which is slower.
  - linux/arm64 images are the rule. Today neither island has one usable for compose (§2).
- **Container runtimes.**
  - Docker Desktop, Podman machine and Colima/Lima are all Linux VMs.
  - Apple `container` 1.0 (macOS 26, Apple silicon) runs one VM per container.
  - Apptainer only runs inside Lima.
- **Toolchain.** Xcode clang has no OpenMP. PhysiCell needs a separate OpenMP g++, and libmuscle with Fortran needs
  GCC ([MUSCLE3 installing](https://github.com/multiscale/muscle3/blob/develop/docs/source/installing.rst.in)).
- **IPC.** `multiprocessing` uses `spawn` (process-bigraph `parallel.py:113-116`). AF_UNIX and loopback TCP both
  work.

### Windows

- **WSL2 is the parity path.**
  - Apptainer runs only inside WSL2 ([admin docs](https://github.com/apptainer/apptainer-admindocs/blob/main/installation.rst)).
  - Docker Desktop uses a WSL2 backend.
  - Anything that needs HPC parity (SIFs, `apptainer exec` launchers) runs in WSL2, not natively.
- **conda-forge gaps on `win-64`** (§2):
  - no PETSc;
  - no MPICH or Open MPI (MS-MPI only);
  - no readdy;
  - no conda LAMMPS;
  - no Chaste.

  FEniCSx has a `win-64` build, but its usual PETSc/MPI stack does not *(whether that build serves our models is
  unverified)*. CompuCell3D, Tissue Forge, ipopt, libsbml, COPASI, libroadrunner, pysces and pyvcell-fvsolver are
  available.
- **Source builds need MSVC.** That covers Smoldyn from source, the Rust/maturin wrappers (MSVC target), AMICI's per-model
  C++ *(unverified)*, and Spack, which only tests MSVC. PhysiCell expects a GNU toolchain *(unverified)*.
- **IPC limits.**
  - `multiprocessing` uses `spawn`.
  - CPython's asyncio does not support `create_unix_server` / `create_unix_connection` on Windows, even though
    Winsock has AF_UNIX since Windows 10 1803 ([asyncio platform support](https://docs.python.org/3/library/asyncio-platforms.html);
    the bpo-33408 PR [was closed](https://github.com/python/cpython/pull/14823)).
  - ZeroMQ `ipc://` needs libzmq ≥ 4.3.3 and fails in some service contexts ([zmq_ipc](https://libzmq.readthedocs.io/en/zeromq4-1/zmq_ipc.html)).
  - `shared_memory` ignores `track` and frees a segment when its last handle closes
    ([shared_memory docs](https://docs.python.org/3/library/multiprocessing.shared_memory.html)).
  - **Loopback TCP or stdio pipes are the portable choices.**
- **Filesystem.**
  - Path-length limits (Spack documents them).
  - uv's default link mode on Windows is `hardlink` ([uv settings](https://docs.astral.sh/uv/reference/settings/)).
  - `.bat`/`.ps1` activation instead of `source`.
- **Frameworks.** Ray is beta. MUSCLE3's C++ libmuscle does not build. Nix and Guix need WSL2.

---

## 4. Tier list

> **Proposal, decided in [plan-environments-epoch2.md](../plan-environments-epoch2.md) EV11.** Status there:
> proposed. Nothing below is decided.

| Tier | Platform | Islands | How | Not available |
|---|---|---|---|---|
| **1** | HPC (Mantis: SLURM, Apptainer) | all | SIF converted from the island's OCI image, pulled by digest; hybrid MPI; EV9 for multi-node | building on the node (no subuid) |
| **1** | Linux (x86_64) | all | native pixi from the lock, or the OCI image under Docker/Podman/Apptainer | — |
| **2** | macOS arm64 | every island that locks for `osx-arm64` | native pixi first; linux/arm64 images for the rest; never amd64 under Rosetta | islands with amd64-only dependencies (today: `registry_env` as built by pbest) |
| **3** | Windows (x86_64) | the subset that locks for `win-64` | native pixi/uv; WSL2 (or Docker Desktop) for the rest | Apptainer natively; PETSc/MPICH; readdy; Chaste; libmuscle |

**How the tiers would be used:**
- **Per platform.** The forest computation (EV4) runs once per platform. An island that does not lock for a platform
  is reported as missing there, not hidden.
- **CI.** Tier 1 platforms run every island's suite. Tiers 2 and 3 run what locks.
- **Linux aarch64** is not a tier of its own. It matters as the source of the arm64 images that tier 2 uses.

---

## Constraints

1. **Apptainer is Linux-only.** Any launcher that needs it on macOS or Windows runs inside a VM (Lima, WSL2). A
   cross-platform worker protocol cannot assume `apptainer exec`.
2. **No arm64 image exists for either island.**
   - `registry_env`'s recipe hard-codes `linux-64` micromamba and conda-forge readdy, which has no arm64 build.
   - viva-pde-particle's compose image is amd64-only.
   - Mac users today get native environments or emulation, and emulation breaks AVX code.
3. **Platform coverage is uneven.**
   - The PDE stack (PETSc, MPICH) has no `win-64` build.
   - libroadrunner, readdy and CompuCell3D have no `linux-aarch64` build.
   - Smoldyn has no stable cp312 wheel anywhere.
   - An island's platform list has to be computed, not assumed.
4. **Mantis cannot build images** with the service user's identity. Builds stay off-node (Kubernetes today, CI or a
   registry later) until subuid is granted.
5. **Portable IPC is loopback TCP or stdio.** AF_UNIX via asyncio and ZeroMQ `ipc://` are not portable to Windows,
   and `shared_memory` semantics differ there.
6. **MPI inside containers follows the hybrid model** on HPC. Dynamic spawning under SLURM is unreliable.
7. **Ray on Windows is beta, and libmuscle does not build on Windows.** Neither can be the only multi-process
   backend if Windows is a target.

## Unknowns

- **Mantis specifics:** the Apptainer/Singularity version, kernel version, subuid policy, Enroot/Pyxis, and OCI mode
  (`plan-container-runtimes.md` §6).
- **Whether stacked read-only overlays work** on the cluster's Apptainer. Apptainer 1.6's `build --overlay` is
  unreleased (experiment X2).
- **Whether the `win-64` FEniCSx build runs the vcell-fenics workloads** without PETSc/MPICH.
- **Direct evidence that FEniCS fails under Rosetta.** The general Rosetta/AVX limit is documented; a FEniCS-specific
  report was not found.
- **MUSCLE3's Python-only operation on Windows**, and on macOS with containers.
- **Whether readdy's arm64 PyPI wheel works** inside an otherwise conda-forge island (ABI of bundled libraries).
- **Which islands actually lock per platform.** Experiment X1 (pixi locks for `linux-64`, `osx-arm64`, `win-64`)
  answers this; the tables above are per package, not per island.
- **Apple `container`** maturity and its fit as a launcher. It was not tested.

## Sources

- [anaconda.org package API](https://api.anaconda.org/package/conda-forge/fenics-dolfinx) (queried 2026-10-13 for every conda row in §2)
- [PyPI JSON API](https://pypi.org/pypi/python-copasi/json) (queried 2026-10-13 for every PyPI row in §2)
- [uv resolution](https://docs.astral.sh/uv/concepts/resolution/), [uv settings](https://docs.astral.sh/uv/reference/settings/)
- [Spack on Windows](https://spack.readthedocs.io/en/latest/windows.html)
- [rix: setting up Nix on macOS](https://docs.ropensci.org/rix/articles/setting-up-macos.html)
- [Grid'5000: Guix](https://grid5000.fr/w/Guix)
- [Docker pricing](https://www.docker.com/pricing/)
- [Help Net Security: Apple container](https://www.helpnetsecurity.com/2026/07/07/apple-container-open-source-linux-mac/)
- [Apptainer admin docs: installation (Windows and Mac)](https://github.com/apptainer/apptainer-admindocs/blob/main/installation.rst)
- [Apptainer CHANGELOG](https://github.com/apptainer/apptainer/blob/main/CHANGELOG.md)
- [Apptainer fakeroot](https://apptainer.org/docs/user/1.4/fakeroot.html), [Apptainer user namespaces](https://apptainer.org/docs/admin/1.5/user_namespace.html), [Apptainer MPI](https://apptainer.org/docs/user/1.5/mpi.html)
- [Sylabs: SingularityCE OCI mode](https://docs.sylabs.io/guides/main/user-guide/oci_runtime.html)
- [Seqera Containers](https://docs.seqera.io/wave/seqera-containers)
- [SchedMD bug 9979](https://support.schedmd.com/show_bug.cgi?id=9979)
- [Ray installation](https://github.com/ray-project/ray/blob/master/doc/source/ray-overview/installation.md), [Ray RuntimeEnv](https://docs.ray.io/en/latest/ray-core/api/doc/ray.runtime_env.RuntimeEnv.html), [Ray on SLURM (community)](https://gitea.com/qu-bit/ray/src/branch/master/doc/source/cluster/slurm.rst)
- [MUSCLE3 installing](https://github.com/multiscale/muscle3/blob/develop/docs/source/installing.rst.in)
- [MongoDB SERVER-56728 (Rosetta and AVX)](https://jira.mongodb.com/browse/SERVER-56728), [docker/for-mac#6620](https://github.com/docker/for-mac/issues/6620)
- [PhysiCell releases](https://github.com/MathCancer/PhysiCell/releases)
- [asyncio platform support](https://docs.python.org/3/library/asyncio-platforms.html), [cpython PR 14823](https://github.com/python/cpython/pull/14823)
- [libzmq `zmq_ipc`](https://libzmq.readthedocs.io/en/zeromq4-1/zmq_ipc.html)
- [multiprocessing.shared_memory](https://docs.python.org/3/library/multiprocessing.shared_memory.html)
- [viva-pde-particle `pixi.toml`](https://github.com/vivarium-collective/viva-pde-particle/blob/main/pixi.toml), [`build-and-push.yml`](https://github.com/vivarium-collective/viva-pde-particle/blob/main/.github/workflows/build-and-push.yml)
