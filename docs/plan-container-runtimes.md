# Container runtimes and image management on HPC

**Status:** working document, opened 2026-09-11, substantially revised 2026-09-12 after review. Part 1 and Part 2
are measured against this repository. Part 4 states a **provisional** direction that is explicitly contingent on
questions only the cluster administrators can answer (Part 5). Nothing here is committed, and nothing has been tested
against `compose.cam.uchc.edu`.

**Claims about third-party runtimes were verified against upstream documentation on 2026-09-12** where a citation
appears; claims without one are reasoning, not evidence, and are marked. Sources are listed at the end.

Related: [plan-testing.md](plan-testing.md) group F, which made the container build path testable in CI for the first
time; tracker row `A3.4.oci` in [the grant tracker](grant/trd3/tracking/TRACKER.md).

---

## 1. The invariant this is really about

Everything below is downstream of one architectural choice, and it is worth stating before any runtime is named.

> **The OCI image digest is the identity of an executable environment. Anything a runtime materialises locally —
> an Enroot `.sqsh`, an Apptainer `.sif`, an extracted OCI bundle, a microVM rootfs — is a cache representation and
> must never acquire independent identity in our domain model.**

Today we violate this. The md5 of a generated Apptainer definition file is `container_def_hash`, and that string is
the identity of a `SimulatorVersion`: a non-nullable column on the `simulator` table, the Docker Hub tag we pull
from, the name of the `.def` file, the name of the `.sif`, and part of the SLURM job name. So the thing that
identifies a simulator is the *recipe*, while the thing that runs is a *separate artifact* that may or may not exist
yet — and `download_container` and `build_container` are two different ways of reaching the same state with nothing
reconciling them.

Under the invariant, a `SimulatorVersion` would carry a repository and a digest, and each execution backend would
keep its own cache keyed by that digest. Those caches can be deleted and regenerated without changing what a
simulator *is*, which makes a future runtime swap nearly free. This reframing is the most valuable outcome of the
review that prompted this revision, and it matters more than which runtime we pick.

---

## 2. What the current path costs

Measured in this repository on 2026-09-11.

**The pipeline.** `pbest` generates an Apptainer definition file from a dependency set; its md5 is the simulator
identity. An unseen hash triggers a SLURM job running `singularity build --fakeroot` on a named build node before
any science can run. `download_container` instead runs `singularity pull` from
`docker://ezqvalencia/registry_env:<hash>`. Results are `.sif` files under `images/`.

1. **A build step that can fail, and a queue wait before any science runs.** A new dependency set means a job that
   installs packages before the simulation starts. It is the slowest and most failure-prone part of a first run.
2. **Two identities for one thing**, as above. This is the root problem.
3. **No layer sharing anywhere in our pipeline.** A `.sif` is a single flattened SquashFS image, so twenty
   simulators sharing a Python base store it twenty times. Note the careful form of this claim: moving to OCI does
   not automatically give layer sharing *on the compute node* either — see §3.1.
4. **`--fakeroot` needs the host to cooperate.** It maps the builder into a user namespace and needs a subordinate
   id range; our test cluster needed `/etc/subuid` populated before a build would run. A production cluster may
   refuse user namespaces outright.
5. **The format is ours alone.** The registry, CI, the `docker-process` work and the platform service all speak
   OCI. Apptainer is the only place that does not.

**What already works and helps.** The test cluster pulls `docker://` images, builds definition files with
`--fakeroot`, and runs the result from inside a SLURM job, verified on every pull request by
`tests/simulation/test_container_lifecycle.py`. Any runtime change can therefore be measured against a working
baseline rather than against nothing.

---

## 3. The options

### 3.1 Trusted tier: run OCI images unprivileged, at full speed

| Option | Shape | Why it might fit | Why it might not |
|---|---|---|---|
| **Enroot + Pyxis** | Enroot *imports* an OCI image and converts it to a SquashFS `.sqsh`, then `create` unpacks that into a rootfs; Pyxis is a SLURM SPANK plugin adding `--container-image` to `srun` | Purpose-built for SLURM, no daemon, no setuid. Pyxis advertises "layers caching and layers sharing across users", so sharing happens in the *download cache*. The OCI digest stays the source identity | Needs an administrator to install the SPANK plugin. Enroot is explicitly an *enhanced unprivileged chroot*, so it is not an isolation boundary |
| **Native SLURM OCI** | SLURM 21.08+ has `--container` backed by `oci.conf`, with documented configurations for runc, crun, Singularity, Charliecloud and Enroot; all containers "run under unprivileged (i.e. rootless) invocation" | No third-party plugin: the scheduler itself supports OCI | Decisive limitation: "Slurm will not transfer the OCI container bundle to the execution nodes. The bundle must already exist on the requested path on the execution node." Image distribution and caching is left entirely to site tooling |
| **Podman, or SLURM `scrun`** | Rootless, daemonless, OCI-native with real layered local storage. `scrun` lets `docker run` / `podman run` submit SLURM jobs | Same tool on a laptop and the cluster; genuine layer reuse | More general-purpose machinery than HPC needs; the storage driver on a shared network filesystem is the usual sticking point |
| **Apptainer OCI mode** | Apptainer 1.3+ runs OCI images and can store them as OCI-SIF | Smallest change: keeps the runtime administrators already trust while dropping the bespoke definition file | Keeps a second representation alive, which is the thing we are trying to stop maintaining |
| **Sarus** | An HPC container runtime built around workload managers, parallel filesystems, OCI images and GPU integration | A serious, purpose-built HPC OCI runtime; near-native CUDA performance is published | Loses to Pyxis on SLURM ergonomics and ecosystem momentum, not on capability |
| **Charliecloud** | Minimal unprivileged OCI runner | Very few moving parts | Less complete image-management story |

*Not shortlisted:* udocker solves a different problem (user-space execution without any privileged support) and is not
in the same architectural class as the above.

**The correction worth internalising.** It is tempting to say Enroot means "no build step, the image is the
artifact". That is too strong. Enroot still performs an import that produces a flattened `.sqsh`. What changes is
*who owns that step*: it becomes a runtime-managed cache operation keyed by the image, rather than an application
build stage that mints a new artifact with its own identity. The pipeline goes from

`dependencies → generate .def → queue build job → build SIF → assign SIF identity → execute`

to

`OCI digest → registry → runtime-managed import and cache → execute`

The preparation cost does not vanish. It moves out of our domain model, which is the point.

### 3.2 Untrusted tier: isolate the workload, not just the filesystem

Namespace-based runtimes are not an isolation boundary for hostile code; Enroot says as much about itself. For
untrusted work the boundary should be a guest kernel, so the candidate is best named as an **architecture** rather
than a product: **a KVM-backed lightweight VM, provisionally Kata Containers with QEMU.**

| Option | Why it might fit | Why it might not |
|---|---|---|
| **Kata + QEMU/KVM** | OCI-compatible interface with a per-workload guest kernel, so the image story does not change. Kata's own hypervisor table marks QEMU as supporting GPU, TDX and SEV-SNP, and calls it "the best supported hypervisor for NVIDIA-based GPUs" | Kata's standard integration path is containerd/CRI-O/Kubernetes. We found **no** mature SLURM↔Kata integration comparable to Pyxis, so the scheduler integration is genuine engineering work. Needs KVM on compute nodes |
| **Kata + Cloud Hypervisor or Firecracker** | Smaller attack surface, faster boot | Kata's table marks both as **no GPU support**, against QEMU's yes. For workloads that may need GPUs, shared filesystems or RDMA, these are a later optimisation for CPU-only cases, not the default |
| **gVisor** | A user-space kernel intercepting syscalls, needing no hardware virtualisation, and it has moved a long way: NVIDIA GPU support via `nvproxy`, plus RDMA work | It loses not because it "may not work" but because it mediates the host ABI rather than providing a real guest kernel. For arbitrary third-party scientific code, a guest kernel is the easier boundary to reason about, and gVisor's RDMA support is still developing and hardware-specific |

### 3.3 What "trusted" should mean

Trust is a property of the *executable content*, not of who handed us an image. A user-supplied script running inside
our own image is still arbitrary user code.

- **Trusted:** all executable content in the workload came from an image or package built through an approved
  BioSimulations supply chain, or has been explicitly admitted to the trusted tier.
- **Untrusted:** the workload can execute arbitrary user-supplied code — scripts, binaries, images, plugins, or
  native extensions.

The two tiers optimise for opposite things and that is deliberate. Trusted execution prioritises negligible overhead
and compatibility with MPI, GPUs, RDMA and parallel filesystems. Untrusted execution prioritises containing hostile
or compromised code, accepting startup and resource overhead to get it.

Note what this implies for the composition work: the moment a composite can carry a user-supplied process, it is an
untrusted workload by this definition, whatever image it runs in.

### 3.4 Image management, the half that is easy to forget

- **Registry.** Today: a personal Docker Hub account (`ezqvalencia/registry_env`), plus GHCR for the service image.
  A personal namespace holding scientific artifacts is a durability risk worth closing regardless of runtime.
- **Identity.** §1. The single most invasive change, and the one that pays for itself.
- **Caching.** Pulling gigabytes per job does not scale. On a shared filesystem the cache design matters more than
  the runtime choice.
- **Provenance.** Reproducing a five-year-old result means the digest still resolving: pinning, a mirror, and
  possibly Zenodo archival as we already do for releases.

---

## 4. Provisional direction, and what would overturn it

**Provisional, not decided.** Every line here is contingent on Part 5, questions 1 to 3. We cannot select a runtime
that requires an administrator to install a SPANK plugin, or KVM on compute nodes, before asking them whether they
will.

1. **The OCI digest is the contract.** Adopt the §1 invariant first. It is independent of every runtime choice
   below, it is the change that makes the others cheap, and it can begin now.
2. **Trusted tier: Enroot + Pyxis, provisionally.** Best SLURM fit, no privileged daemon, image acquisition and
   caching integrated with job execution, and the BioSimulations-facing artifact stays OCI-native.
3. **Untrusted tier: a KVM-backed microVM architecture, provisionally Kata with QEMU.** Named as an architecture
   because the SLURM integration is unsolved.

| Candidate | Trusted HPC | Untrusted | OCI-native | SLURM fit | Standing |
|---|---|---|---|---|---|
| Enroot + Pyxis | excellent | poor | excellent | excellent | **provisional trusted tier** |
| Native SLURM OCI + crun | very good | poor | good | excellent | image distribution left to us |
| Podman / `scrun` | good | poor | excellent | good | storage and user-namespace operations |
| Apptainer (incl. OCI mode) | excellent | poor | moderate | excellent | keeps a second representation alive |
| Sarus | excellent | poor | excellent | very good | strong; loses on ecosystem fit |
| Charliecloud | very good | poor | good | very good | thinner image management |
| Kata + QEMU/KVM | moderate | excellent | excellent | needs integration | **provisional untrusted tier** |
| gVisor | moderate | very good | excellent | needs integration | mediates the ABI rather than providing a kernel |
| Firecracker / Cloud Hypervisor | moderate | excellent | needs orchestration | needs integration | no GPU support in Kata's table |

**What would overturn this.** Administrators declining the Pyxis plugin (falls back to native SLURM OCI plus our own
distribution, or Apptainer OCI mode). No KVM on compute nodes (untrusted work needs dedicated nodes, a separate
partition, or does not happen here). User namespaces disabled (most of the trusted tier becomes unavailable and the
question changes shape entirely).

---

## 5. Open questions

The first three are for the cluster administrators and everything else depends on them.

1. What does `compose.cam.uchc.edu` have installed, and what will its administrators support? Pyxis needs a SPANK
   plugin; rootless Podman needs `newuidmap` and user namespaces; Kata needs KVM on compute nodes.
2. Are user namespaces enabled at all? `--fakeroot` works today, which is evidence they are, but policy can change.
3. Is there a shared image cache, and what is our quota?
4. Do we need untrusted execution now, or is it a Y4–Y5 concern? This decides whether §3.2 belongs in this plan.
5. Do we keep `.sif` as a fallback, or commit to one runtime? A period of both is likely; `ContainerizationEngine`
   already has `NONE`, `DOCKER`, `APPTAINER` and `BOTH` arms to hang that on.
6. The migration: `container_def_hash` is a non-nullable column and is used as the image tag, the `.def` name, the
   `.sif` name and part of the job name. Moving identity to a digest is a schema change plus a backfill, and needs
   its own plan.
7. Can the test cluster model the chosen runtime, so this is verified in CI the way the Apptainer path now is?

## 6. Next step

Answer questions 1 to 3 by asking the administrators, because everything below them depends on the answers. In
parallel, and at no cost to them, adopt the §1 invariant in the data model and prototype one simulator as a plain
OCI image run through `ContainerizationEngine.DOCKER` on the test cluster, comparing pull time, disk footprint and
startup against the `.sif` path already measured there. That produces a number to argue from rather than a
preference.

---

## Sources

Verified 2026-09-12.

- [Slurm containers guide](https://slurm.schedmd.com/containers.html) — `--container`, `oci.conf`, rootless
  invocation, `scrun`, and the bundle-distribution limitation.
- [Enroot usage documentation](https://github.com/NVIDIA/enroot/blob/master/doc/usage.md) — `import` producing a
  `.sqsh`, `create` unpacking to a rootfs.
- [NVIDIA Pyxis](https://github.com/NVIDIA/pyxis) — `--container-image`, layer caching and sharing across users.
- [Kata Containers hypervisors](https://github.com/kata-containers/kata-containers/blob/main/docs/hypervisors.md) —
  the hypervisor capability table and the QEMU/GPU recommendation.

Not independently verified, and flagged as such above: the absence of a mature SLURM↔Kata integration (a search on
2026-09-12 found none, which is weaker than knowing none exists); Sarus CUDA performance; gVisor RDMA maturity.
