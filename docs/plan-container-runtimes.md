# Container runtimes and image management on HPC

**Status:** working document, opened 2026-09-11, revised 2026-09-12 after review, and revised again the same day once
it was established that **no workload here needs a GPU**. That single constraint changed the untrusted-tier
conclusion, so §5 no longer says what it said this morning. Nothing is committed, and nothing has been tested against
`compose.cam.uchc.edu`.

**Claims about third-party runtimes carry a citation and were verified against upstream documentation on
2026-09-12.** Claims without one are reasoning, not evidence, and are marked. Sources are listed at the end.

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
yet, and `download_container` and `build_container` are two different ways of reaching the same state with nothing
reconciling them.

There is a sharper version of this objection, evidenced in §3: the recipe hash does not merely *differ* from the
image identity, it **claims something false**. The generated definition is not deterministic, so the same hash can
name materially different images built at different times.

Under the invariant, a `SimulatorVersion` carries a repository and a digest, and each execution backend keeps its own
cache keyed by that digest. Those caches can be deleted and regenerated without changing what a simulator *is*, which
makes a future runtime swap nearly free. **This is the only recommendation in this document that does not depend on
anything the cluster administrators say, and it should be done first.**

---

## 2. The workload we actually have

This section exists because the answer to "which runtime" is mostly determined by it, and because getting it wrong
imports requirements we do not have.

Read from the production sbatch templates in `simulation_service.py` on 2026-09-12:

| Job | CPUs | Memory |
|---|---|---|
| simulation | 2 | 8 GB |
| batch simulation | 1 | 1 GB |
| container build | 1 | 4 GB |

No `--gres` and no GPU request anywhere in the service. No `--nodes` or `--ntasks` either, so every job is a single
task on a single node by default. No MPI. Every job reads and writes a shared filesystem tree under
`_namespace_path()`: `htclogs/`, `slurm_sbatch/`, `images/`, `sims/`.

**These are ordinary containerised batch jobs that happen to be scheduled by SLURM.** They are not the workloads that
motivated Apptainer, Enroot or Sarus, all of which earn their keep on GPU passthrough, multi-node MPI and parallel
filesystems. Stripping those away, the requirements reduce to four:

1. **Unprivileged execution.** No daemon, no setuid, no root.
2. **Shared filesystem access.** The job must see the namespace tree. This is the constraint that does the most work
   below, and it is the one most easily overlooked.
3. **SLURM integration.** Submitting a containerised job should not mean writing a script that moves files around.
4. **Image distribution and caching.** Getting the image to the compute node, once, and reusing it.

A wider field satisfies that list than satisfies the HPC-flagship list. Rootless Podman and SLURM's native OCI
support are more competitive here than they would be against a GPU-and-MPI requirement.

**Caveat.** This is today's workload. If the composition work produces multi-node composites, or a collaborator
contributes a GPU simulator, the constraint set changes and §4.2 in particular should be re-read.

---

## 3. What the current path costs

**The pipeline.** `pbest` generates an Apptainer definition file from a dependency set; its md5 is the simulator
identity. An unseen hash triggers a SLURM job running `singularity build --fakeroot` on a named build node before any
science can run. `download_container` instead runs `singularity pull` from the configured simulator image repository,
tagged with that hash. Results are `.sif` files under `images/`.

**What the artifact actually is.** Read from the generated definition on 2026-09-12. `registry_env` is a *single*
image holding **every simulator in pbest's default registry**, plus pbest itself as the entry point. "Registry" is
the simulator registry; "env" is the one conda environment they all share.

| Layer | Contents |
|---|---|
| base | `astral/uv:python3.12-bookworm-slim` |
| pbest | cloned from git at the pinned tag, installed into the environment |
| pip simulators | `python-copasi`, `tellurium`, `pb_multiscale_actin`, each version-pinned |
| conda simulator | `readdy` from conda-forge, via micromamba |

Its run script is `micromamba run … python3 /runtime/pbest/main.py "$@"`, so the container is invoked as the pbest
command line. Four simulators, a conda stack and a full Python environment in one artifact is why it is 1.3 GB.

Worth naming: this is the opposite of what Aim 3 promised in `A3.4.docker`, which is each simulator in its own
container exposing the Process Interface. The tracker already records the same whole-composite-in-one-image pattern
in `pbest containerize` and `bsew`, so it is consistent rather than surprising.

1. **A build step that can fail, and a queue wait before any science runs.** A new dependency set means a job that
   installs packages before the simulation starts. It is the slowest and most failure-prone part of a first run.
2. **Two identities for one thing**, as in §1. This is the root problem.
3. **No layer sharing anywhere in our pipeline.** A `.sif` is a single flattened SquashFS image, so twenty simulators
   sharing a Python base store it twenty times. Because `registry_env` is monolithic, changing any single pin
   produces an entirely new 1.3 GB artifact that shares nothing with its predecessor. Note the careful form of the
   claim: moving to OCI does not automatically give layer sharing *on the compute node* either, see §4.1.
4. **`--fakeroot` needs the host to cooperate.** It maps the builder into a user namespace and needs a subordinate id
   range; our test cluster needed `/etc/subuid` populated before a build would run. A production cluster may refuse
   user namespaces outright.
5. **The format is ours alone.** The registry, CI, the `docker-process` work and the platform service all speak OCI.
   Apptainer is the only place that does not.
6. **The identity asserts a reproducibility that does not exist.** This is the sharpest of the six, and the one that
   most directly justifies §1. The md5 identifies the *recipe*, and the recipe is not deterministic: the definition
   runs `apt upgrade -y`, fetches micromamba from a `latest` URL, resolves pbest's own requirements with
   `uv pip compile` at build time, and sits on a mutable base-image tag. Only the four simulator versions are
   pinned. Two builds of the byte-identical definition, months apart, therefore produce different images under the
   same identity.

   An image digest describes what was actually built; a hash of the recipe describes only what was asked for. Here
   the gap is not theoretical, and it is precisely the gap that matters for reproducing a five-year-old result.

**What already works and helps.** The test cluster pulls `docker://` images, builds definition files with
`--fakeroot`, and runs the result from inside a SLURM job, verified on every pull request by
`tests/simulation/test_container_lifecycle.py`. Any runtime change can be measured against a working baseline.

---

## 4. The options

### 4.1 Trusted tier: run OCI images unprivileged

| Option | Shape | Why it might fit | Why it might not |
|---|---|---|---|
| **Enroot + Pyxis** | Enroot *imports* an OCI image to a SquashFS `.sqsh`, then `create` unpacks it to a rootfs; Pyxis is a SLURM SPANK plugin adding `--container-image` to `srun` | Purpose-built for SLURM. Pyxis advertises "layers caching and layers sharing across users", so it answers requirement 4 directly. The OCI digest stays the source identity | Needs an administrator to install the SPANK plugin. Enroot is explicitly an *enhanced unprivileged chroot*, so it is not an isolation boundary. **Its GPU integration, a large part of its general appeal, is worth nothing to us** |
| **Native SLURM OCI** | SLURM 21.08+ has `--container` backed by `oci.conf`, with documented configurations for runc, crun, Singularity, Charliecloud and Enroot; all containers "run under unprivileged (i.e. rootless) invocation" | No third-party plugin: the scheduler itself supports OCI, satisfying requirements 1 and 3 | Fails requirement 4 by design: "Slurm will not transfer the OCI container bundle to the execution nodes. The bundle must already exist on the requested path on the execution node." Distribution and caching become ours to build |
| **Podman, or SLURM `scrun`** | Rootless, daemonless, OCI-native with real layered local storage. `scrun` lets `docker run` / `podman run` submit SLURM jobs | Same tool on a laptop and the cluster; genuine layer reuse. **More competitive against our four requirements than against a GPU-and-MPI list** | The storage driver on a shared network filesystem is the usual sticking point; user-namespace configuration becomes cluster operations |
| **Apptainer OCI mode** | Apptainer 1.3+ runs OCI images and can store them as OCI-SIF | Smallest change: keeps the runtime administrators already trust while dropping the bespoke definition file | Keeps a second representation alive, which is the thing we are trying to stop maintaining |
| **Sarus** | An HPC container runtime built around workload managers, parallel filesystems, OCI images and GPU integration | A serious, purpose-built HPC OCI runtime | Most of what distinguishes it is aimed at requirements we do not have |
| **Charliecloud** | Minimal unprivileged OCI runner | Very few moving parts, and CPU-only simplicity is now a virtue rather than a limitation | Thinner image-management story, so requirement 4 is partly ours again |

*Not shortlisted:* udocker solves a different problem, user-space execution without any privileged support, and is not
in the same architectural class.

**The correction worth internalising.** It is tempting to say Enroot means "no build step, the image is the artifact".
That is too strong: Enroot still performs an import producing a flattened `.sqsh`. What changes is *who owns that
step*. It becomes a runtime-managed cache operation keyed by the image, rather than an application build stage that
mints a new artifact with its own identity. The pipeline goes from

`dependencies → generate .def → queue build job → build SIF → assign SIF identity → execute`

to

`OCI digest → registry → runtime-managed import and cache → execute`

The preparation cost does not vanish. It moves out of our domain model, which is the point.

### 4.2 Untrusted tier: isolate the workload, not just the filesystem

Namespace-based runtimes are not an isolation boundary for hostile code; Enroot says as much about itself. **This
section changed once the GPU requirement was removed, and the reasoning is worth following, because the constraint
that decides it is not the one that looked decisive.**

| Option | Why it might fit | Why it might not |
|---|---|---|
| **gVisor** | A user-space kernel intercepting syscalls. **It needs no hardware virtualisation:** `systrap` has been the default platform since mid-2023 and uses `seccomp`'s `SECCOMP_RET_TRAP` to intercept syscalls, and is documented as "a better choice when running inside a VM, or on a machine without virtualization support". That removes the hardest thing to ask of a shared university cluster. Its weaker areas, GPU and RDMA, are now irrelevant to us. It presents host directories to the sandbox, satisfying requirement 2 | It mediates the host ABI rather than providing a real guest kernel, so the boundary is harder to reason about than a VM's, and compatibility is a per-syscall question rather than a general guarantee |
| **Kata + QEMU/KVM** | A per-workload guest kernel behind an OCI-compatible interface: the strongest boundary of the three, and the easiest to explain to a security reviewer | Needs KVM on compute nodes, which is a substantial administrative ask. Kata's standard integration path is containerd/CRI-O/Kubernetes, and we found **no** mature SLURM equivalent to Pyxis, so scheduler integration is real engineering work |
| **Kata + Firecracker or Cloud Hypervisor** | Small attack surface, fast boot: Firecracker documents "a < 125 ms startup time and a < 5 MiB memory footprint" | **Ruled out by requirement 2, not by GPU.** Firecracker ships "only 6 emulated devices … virtio-net, virtio-balloon, virtio-block, virtio-vsock, serial console, and a minimal keyboard controller", none of which shares a filesystem: no virtio-fs, no 9p. Every one of our jobs reads and writes the shared namespace tree |

**Why this reversed.** The earlier draft ranked QEMU first because Kata's hypervisor table marks Firecracker and
Cloud Hypervisor as having no GPU support. With no GPU requirement that argument evaporates, and it would have been
easy to promote Firecracker on boot time. The firmer objection is filesystem sharing, which Firecracker's own FAQ
settles and which has nothing to do with GPUs. The right conclusion survived, but the reason it was originally given
for was the wrong one.

**Provisional preference: gVisor first, Kata with QEMU as the stronger-boundary fallback.** gVisor removes the KVM
dependency, which was the single largest feasibility risk in this tier, and the capabilities it trades away are ones
we do not use. Choose Kata instead if a review concludes that only a separate guest kernel is an acceptable boundary
for arbitrary third-party code, and accept the KVM conversation that comes with it.

### 4.3 What "trusted" should mean

Trust is a property of the *executable content*, not of who handed us an image. A user-supplied script running inside
our own image is still arbitrary user code.

- **Trusted:** all executable content came from an image or package built through an approved BioSimulations supply
  chain, or has been explicitly admitted to the trusted tier.
- **Untrusted:** the workload can execute arbitrary user-supplied code, whether scripts, binaries, images, plugins or
  native extensions.

The two tiers optimise for opposite things, deliberately. Trusted execution prioritises negligible overhead.
Untrusted execution prioritises containing hostile or compromised code and accepts overhead to get it.

Note what this implies for the composition work: the moment a composite can carry a user-supplied process, it is an
untrusted workload by this definition, whatever image it runs in.

### 4.4 Image management, the half that is easy to forget

- **Registry.** This turned out to be the most urgent item, and it is now partly addressed. The simulator images
  lived under a **personal Docker Hub account belonging to someone who has since left**, hardcoded in two places in
  `models.py`. That is a durability risk in the ordinary sense and an access risk in a sharper one, and the account
  is not to be used. It is now the `simulator_image_repository` setting, defaulting to
  `ghcr.io/biosimulations/registry_env` alongside the service image. **No image is published there yet**, so until
  one is, every first run of a simulator takes the build fallback in
  `handlers._download_or_build_container`. That is the designed behaviour when a download fails, not a regression:
  the old location had no image for the current pbest pin either. Publishing images under the organisation account
  is an operational task this document cannot do.
- **Identity.** §1. The most invasive change, and the one that pays for itself.
- **Caching.** Requirement 4. On a shared filesystem the cache design matters more than the runtime choice.
- **Provenance.** Reproducing a five-year-old result means the digest still resolving: pinning, a mirror, and
  possibly Zenodo archival as we already do for releases.

---

## 5. Provisional direction, and what would overturn it

**Provisional, not decided.** Contingent on §6 questions 1 to 3.

1. **The OCI digest is the contract.** Adopt the §1 invariant first. Independent of every runtime choice, and it can
   begin now.
2. **Trusted tier: Enroot + Pyxis, provisionally.** Best SLURM fit, no privileged daemon, and it is the only
   candidate that answers requirement 4 out of the box. Note that its GPU integration, usually its headline feature,
   counts for nothing here, so the margin over Podman and native SLURM OCI is narrower than it first appeared.
3. **Untrusted tier: gVisor, provisionally, with Kata and QEMU as the stronger-boundary alternative.** Changed from
   the earlier draft: without a GPU requirement, gVisor's compatibility gaps stop mattering and its lack of a KVM
   dependency becomes decisive.

| Candidate | Trusted fit | Untrusted fit | OCI-native | SLURM fit | Standing under our four requirements |
|---|---|---|---|---|---|
| Enroot + Pyxis | excellent | poor | excellent | excellent | **provisional trusted tier**; answers requirement 4 |
| Native SLURM OCI + crun | very good | poor | good | excellent | fails requirement 4 by design |
| Podman / `scrun` | good | poor | excellent | good | closer than it looks; storage on shared FS is the risk |
| Apptainer, incl. OCI mode | excellent | poor | moderate | excellent | keeps a second representation alive |
| Sarus | very good | poor | excellent | very good | its differentiators target requirements we lack |
| Charliecloud | very good | poor | good | very good | simplicity now a virtue; thinner on requirement 4 |
| gVisor | moderate | very good | excellent | needs integration | **provisional untrusted tier**; no KVM needed |
| Kata + QEMU/KVM | moderate | excellent | excellent | needs integration | strongest boundary; needs KVM and integration work |
| Firecracker / Cloud Hypervisor | poor | excellent | needs orchestration | needs integration | no filesystem sharing, fails requirement 2 |

**What would overturn this.** Administrators declining the Pyxis plugin sends the trusted tier to native SLURM OCI
plus our own distribution, or to Apptainer OCI mode. User namespaces being disabled removes most of the trusted tier
and changes the question entirely. A security review insisting on a guest kernel moves the untrusted tier to Kata and
reopens the KVM conversation. A GPU or multi-node requirement arriving through the composition work reopens §4.2 and
much of §4.1.

---

## 6. Open questions

The first three are for the cluster administrators and most things depend on them.

1. What does `compose.cam.uchc.edu` have installed, and what will its administrators support? Pyxis needs a SPANK
   plugin; rootless Podman needs `newuidmap` and user namespaces. KVM is now only needed if the untrusted tier goes
   to Kata rather than gVisor.
2. Are user namespaces enabled at all? `--fakeroot` works today, which is evidence they are, but policy can change.
3. Is there a shared image cache, and what is our quota?
4. Do we need untrusted execution now, or is it a Y4–Y5 concern? This decides whether §4.2 belongs in this plan.
5. Do we keep `.sif` as a fallback, or commit to one runtime? A period of both is likely; `ContainerizationEngine`
   already has `NONE`, `DOCKER`, `APPTAINER` and `BOTH` arms to hang that on.
6. The migration: `container_def_hash` is a non-nullable column and is used as the image tag, the `.def` name, the
   `.sif` name and part of the job name. Moving identity to a digest is a schema change plus a backfill and needs its
   own plan.
7. Can the test cluster model the chosen runtime, so this is verified in CI the way the Apptainer path now is?

## 7. Next step

Answer questions 1 to 3 by asking the administrators. In parallel, and at no cost to them, adopt the §1 invariant in
the data model and prototype one simulator as a plain OCI image run through `ContainerizationEngine.DOCKER` on the
test cluster, comparing pull time, disk footprint and startup against the `.sif` path already measured there. That
produces a number to argue from rather than a preference.

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
- [Firecracker FAQ](https://github.com/firecracker-microvm/firecracker/blob/main/FAQ.md) — the six-device model, the
  absence of filesystem sharing, and the startup and footprint figures.
- [gVisor platforms](https://gvisor.dev/docs/architecture_guide/platforms/) — `systrap` as the default since mid-2023,
  `SECCOMP_RET_TRAP` interception, and running without virtualisation support.

Workload figures in §2 are read from `compose_api/simulation/simulation_service.py`. Not independently verified, and
flagged as such above: the absence of a mature SLURM↔Kata integration, which a search on 2026-09-12 failed to find,
weaker than knowing none exists.
