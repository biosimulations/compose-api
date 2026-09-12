# Container runtimes and image management on HPC

**Status:** seed document, opened 2026-09-11 at the user's request. Part 1 is measured against this repository and
its test cluster. Parts 2 and 3 are options and open questions, not decisions, and nothing here has been researched
against the production cluster at `compose.cam.uchc.edu` — several of the questions below can only be answered by
asking its administrators.

**The thesis to test.** If every simulator is an OCI image and nothing else, we can stop maintaining a second image
format and a second build step. The special build disappears, layers are shared instead of duplicated, and one
artifact serves the laptop, CI, and the cluster.

Related: [plan-testing.md](plan-testing.md) group F, which made the build path testable in CI for the first time;
tracker row `A3.4.docker` in [the grant tracker](grant/trd3/tracking/TRACKER.md), which promises "each simulator in
its own container exposing the Process Interface".

---

## Part 1. What we do today, and what it costs

Measured in this repository on 2026-09-11.

**The pipeline.** `pbest` generates an Apptainer definition file from a dependency set. The md5 of that text is
`get_singularity_hash`, and **that hash is the identity of a `SimulatorVersion`** (`hpc_utils.py`). An unseen hash
triggers a build job before the simulation runs. `build_container` writes an sbatch script that runs
`singularity build --fakeroot` on a named build node; `download_container` runs `singularity pull` from
`docker://ezqvalencia/registry_env:<hash>`. Results are `.sif` files under `images/` in the namespace directory.

**Five costs, in rough order of how much they hurt.**

1. **A build step that can fail, and a queue wait before any science runs.** A new dependency set means a SLURM job
   that installs packages, on a build node, before the simulation can start. It is the slowest and most failure-prone
   part of a first run.
2. **Two identities for one thing.** The definition-file hash identifies the simulator, but the image that actually
   runs is a separate artifact that may or may not exist yet. `download_container` and `build_container` are two ways
   to reach the same state, and nothing reconciles them.
3. **No layer sharing.** A `.sif` is a single flattened SquashFS image. Twenty simulators that share a Python base
   store that base twenty times, on shared filesystem quota. OCI layers are content-addressed and shared.
4. **`--fakeroot` needs the host to cooperate.** It maps the builder into a user namespace and needs a subordinate id
   range. Our test cluster needed `/etc/subuid` populated before a build would run at all; a production cluster may
   refuse user namespaces entirely.
5. **The format is ours alone.** Every other part of the stack — the registry, CI, the `docker-process` work, the
   platform service — speaks OCI. Apptainer is the only place that does not.

**What is already true and helps.** The test cluster (`tests/fixtures/slurm_cluster/`) pulls `docker://` images,
builds definition files with `--fakeroot`, and runs the result from inside a SLURM job, all verified in CI by
`tests/simulation/test_container_lifecycle.py`. So the machinery is exercised on every pull request now, which means
a runtime change can be evaluated against a working baseline rather than against nothing.

---

## Part 2. The options

Grouped by the distinction the user drew: **trusted** images we build and publish, versus **untrusted** images a user
supplies. These are not exclusive; a plausible end state runs two runtimes side by side and chooses per job.

### 2.1 Trusted: run OCI images directly, unprivileged

| Option | Shape | Why it might fit | What to check |
|---|---|---|---|
| **Enroot + Pyxis** | NVIDIA's pair. Enroot converts an OCI image to an unprivileged flattened rootfs; Pyxis is a SLURM SPANK plugin adding `--container-image` to `srun`/`sbatch` | Purpose-built for SLURM, no daemon, no setuid, no build step: the image *is* the artifact. Submission becomes a flag rather than a script that moves files around | Needs the admin to install the SPANK plugin. Whether image caching is per-user or shared, and where it lands on our filesystem |
| **Podman** | Rootless, daemonless, OCI-native, layer-sharing | Same tool on a laptop and the cluster; real layer reuse; standard `podman build` replaces the definition file | Rootless needs user namespaces and `newuidmap`; storage driver on a shared network filesystem is the usual sticking point |
| **Apptainer OCI mode** | Apptainer 1.3+ can run OCI images and store them as OCI-SIF | Smallest change: keeps the runtime the admins already trust while dropping the bespoke definition file | Whether the cluster's Apptainer is new enough, and whether OCI-SIF actually shares layers in our usage |
| **Charliecloud / Sarus / udocker** | Lighter-weight unprivileged OCI runners | Fewer moving parts than Podman | Smaller communities; less likely already installed |

### 2.2 Untrusted: isolate the workload, not just the filesystem

Relevant the moment a user can supply their own image or their own process code, which the composition work points
directly at.

| Option | Shape | Why it might fit | What to check |
|---|---|---|---|
| **Kata Containers** | OCI runtime that starts each container in a lightweight VM | Hardware-backed isolation with an OCI interface, so the image story does not change | Needs nested virtualisation or bare metal with KVM. Unlikely on a shared HPC login node; may need dedicated nodes |
| **Firecracker microVM** | Minimal VMM, very fast boot | Strong isolation, small attack surface | Not an OCI runtime by itself; needs an image-conversion layer |
| **gVisor** | User-space kernel intercepting syscalls | No virtualisation requirement | Syscall compatibility and performance cost for numerical workloads are the open questions |

### 2.3 Image management, which is the half that is easy to forget

Choosing a runtime does not answer where images live or how they are named.

- **Registry.** Today: Docker Hub under a personal account (`ezqvalencia/registry_env`), plus GHCR for the service
  image. A personal namespace for scientific artifacts is a durability risk worth closing regardless of runtime.
- **Identity.** If the image is the artifact, the natural identity is its content digest, not the md5 of a definition
  file. That is a change to `SimulatorVersion` and everything that keys off `container_def_hash`, so it is the
  single most invasive item here and deserves its own decision.
- **Caching.** Pulling a multi-gigabyte image per job does not scale. Enroot, Podman and Apptainer each cache
  differently, and on a shared filesystem the cache design matters more than the runtime.
- **Provenance.** Reproducing a five-year-old result means the image still resolving. Digest pinning, a mirror, and
  possibly Zenodo archival, in line with what we already do for releases.

---

## Part 3. Open questions

Ordered so the cheap ones come first; the first three are cluster questions we cannot answer from here.

1. What does `compose.cam.uchc.edu` actually have installed, and what will its administrators support? Enroot and
   Pyxis need a SPANK plugin; rootless Podman needs `newuidmap` and user namespaces; Kata needs KVM.
2. Are user namespaces enabled at all? `--fakeroot` works there today, which is evidence they are, but a policy can
   change under us.
3. Is there a shared image cache, and what is our quota?
4. Do we need untrusted execution *now*, or is it a Y4–Y5 concern? The answer decides whether 2.2 is in this plan or
   a later one.
5. Would we keep `.sif` as a fallback, or commit to one runtime? A period of both is likely, and the abstraction that
   makes that bearable is `ContainerizationEngine`, which already exists and already has a `DOCKER` arm.
6. Does the identity change from definition-file hash to image digest, and if so, what is the migration for existing
   `SimulatorVersion` rows?
7. Can the test cluster model the chosen runtime, so this is verified in CI the way the Apptainer path now is?

## Next step, if this is taken up

Answer questions 1–3 by asking the cluster administrators, because every option below them depends on the answers.
In parallel, and at no cost to them, prototype one simulator as a plain OCI image run through
`ContainerizationEngine.DOCKER` on the test cluster, and compare pull time, disk footprint and startup against the
`.sif` path already measured there. That gives a number to argue from rather than a preference.
