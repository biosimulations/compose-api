# Environment builds: jobs and artifacts of their own

**Status (2026-10-13): plan agreed; phase 1 in review.** One PR per phase, merged with a merge commit; each PR updates the
table below. A merge deploys nothing by itself: the next release's image ships it (CLAUDE.md, "Deploys are GitOps").

| Phase | What | State |
|---|---|---|
| 1 | Runs carry their backend and external job id (`hpcrun.backend`, `hpcrun.external_id`); the monitor asks each backend about its own runs | in review |
| 2 | `environment_image`: an artifact record per built or pulled image (kind, location, digest, size, the run that produced it, available); "built" means an available artifact | planned |
| 3 | The `k8s` build backend: a Kubernetes Job builds the image (privileged, scratch only) and copies it onto the shared filesystem as the service user | planned |
| 4 | Builds invoked on their own: `POST /environments/{name}/build`, `GET /environments/{name}/images`; a run waits for an in-flight build of its definition instead of starting another | planned |
| 5 | Publish: an image pushed to a registry, recorded as another artifact; a cluster pulls it instead of building | planned |

## Why

The first live SED-ML comparison (2026-10-13, simulations 4578 and 4579) needed a new `registry_env` definition, and
every way the service decides about images showed its limits:

- **The cluster cannot build.** The SLURM build runs `singularity build --fakeroot` on the build node, and the service
  user has no subordinate id range there: `FATAL: could not use fakeroot: no mapping entry found in /etc/subuid for
  svc_compose` (simulator 283). Nothing this repository does fixes that on the node.
- **"Built" was a guess.** Whether a definition was built was read off "some `hpcrun` with this simulator id", of
  any job type and in no order, so a run took a failed build as done and ran without an image. #290 narrowed it to
  "the newest build run completed", still a proxy: a deleted `.sif`, or a build that "completes" without writing
  one, disagrees with the database and nothing notices.
- **A build has no life of its own.** It happens only inside a run's dispatch (`_download_or_build_container`), so
  an image cannot be prepared before a release, backfilled, or published, and two runs needing one definition used
  to build it twice (#290 serializes them within one API process).
- **Images are invisible.** `images/<hash>.def` and `images/<hash>.sif` on the shared filesystem are recorded
  nowhere; `downloaded_containers` records pulls only. The registry's environments (`environments.yaml`, the
  manifests) and the `simulator` rows that build them are not connected.

## What exists (2026-10-13)

- **`simulator`**: an environment's definition (`container_def`), its hash (`container_def_hash`, the identity),
  its engine. Created when a run first needs that definition.
- **`hpcrun`**: one row per job. Polymorphic by `job_type` (`simulation`, `build_container`) and its reference
  (`simulation_id` or `simulator_id`), but SLURM-shaped: `slurmjobid`, SLURM states, polled only by the SLURM
  monitor. A row without `slurmjobid` is never polled.
- **`downloaded_containers`**: a pull of a prebuilt image into a `.sif`.
- **Files**: `<store>/<namespace>/images/<hash>.def` and `<hash>.sif`, the paths the job script runs from.
- **Since #290**: one build at a time per definition hash in one API process, a failed build is tried again, the
  build script works in a private temporary directory, and `GET /results/simulator/build/log` serves the newest
  build's log.

## Decisions

| | Decision | Why |
|---|---|---|
| E1 | **Keep one polymorphic run table** (`hpcrun`), and give each run its **backend** (`slurm`, `k8s`) and **external id** (a SLURM job id, a Kubernetes Job name); `slurmjobid` stays, filled for SLURM runs, until nothing reads it | builds and runs share status, events, traces and the monitor; a second table would duplicate all of it. A build is a run of type `build_container` whose reference is the simulator |
| E2 | **The monitor asks each backend about its own runs**: SLURM by `squeue`/`sacct`, Kubernetes by the Job's conditions (and `FailedCreate` events, for a pod the namespace refuses) | one place updates every run's status; a build's waiter reads the database like a run's |
| E3 | **An artifact table, `environment_image`**: simulator, kind (`sif`, `oci`), location (a path on the shared filesystem, or a registry reference), digest (sha256), size, the producing run (nullable: adopted or pulled), `available`, created and verified times | "built" becomes "an available artifact exists", checkable against the disk or the registry; history survives rebuilds |
| E4 | **Images are write-once**: a build that finds the artifact's file already there adopts it and records it; it never replaces one | a simulator's image is part of what reproduced a result; replacing it under past runs would break that |
| E5 | **Builds are invocable on their own, through the same code as a run's preprocess**: the run path asks for an available image of its definition, joining an in-flight build (a build run of that simulator that has not finished) instead of starting one | backfill, release preparation and publication need it; one path keeps them consistent |
| E6 | **Where to build is a setting** (`build_backend`: `slurm`, `k8s`); the deployment uses `k8s`, since its SLURM nodes cannot build | the SLURM build stays for sites whose nodes can |
| E7 | **The Kubernetes build** runs `apptainer build` as root in a privileged init container that mounts only scratch space and, read-only, the definition; the unprivileged main container copies the image onto the shared filesystem as the service user (the API pod's uid), beside its target and renamed | a definition with a `%post` needs mount namespaces; the privileged process never writes the filesystem the SLURM nodes read, and the writer is the user whose files they are (root squash respected, not bypassed) |
| E8 | **Publishing is a separate, explicit step** that pushes an image to a registry and records an `oci` artifact; the run path prefers pulling a published image over building | a cluster that cannot build can still pull; publication is a decision, not a side effect |

## The model after this

```text
simulator (an environment's definition: hash, engine)
 ├── hpcrun job_type=build_container   (backend slurm|k8s, external_id, status, log)  ── produces ──┐
 ├── environment_image kind=sif  location=<store>/<ns>/images/<hash>.sif  digest, size, available ◄─┘
 ├── environment_image kind=oci  location=ghcr.io/…/registry_env:<hash>    digest (phase 5)
 └── simulation ── hpcrun job_type=simulation (backend slurm, external_id = SLURM job id)
registry environment (environments.yaml: registry_env) ──► its current simulator (by definition hash) ──► its images
```

## Phases

1. **Runs carry their backend.** Columns `hpcrun.backend` (default `slurm`) and `hpcrun.external_id` (text),
   backfilled from `slurmjobid`; migration. `HpcRun` gains both. The monitor groups unfinished runs by backend and
   polls each through a small interface (`poll(runs) -> statuses`); SLURM is today's code moved behind it.
2. **Artifacts.** Table `environment_image`; recorded when a SLURM or Kubernetes build completes (the `.sif`'s
   sha256 and size read through the API pod's mount of the store), when a pull completes (`downloaded_containers`
   stays as the pull's history), and when a build adopts an existing file. "Built" is
   `environment_image(kind=sif, available)`; a verification (`stat` on the mount) marks a missing file unavailable,
   at lookup and on a schedule. A backfill records the `.sif` files already on the store for existing simulators.
3. **The `k8s` backend.** `compose_api/simulation/build_k8s.py` (the Job of E7, `ghcr.io/apptainer/apptainer:1.3.6`),
   a `compose-api-builds` service account and Role (Jobs, pods, logs, events), settings `build_backend` and
   `build_k8s_*`; the rke deployment sets `build_backend=k8s`. The build log route reads the Job's pods' logs.
4. **Builds on their own.** `POST /environments/{name}/build` (the environment's current definition; answers the
   build run, or the available image when there is one), `GET /environments/{name}/images`, and the same for a
   simulator id. The run path calls the same function and waits on the build run's status in the database (any API
   process, not only the one that started it). The web app's environment page shows whether its image is built.
5. **Publish.** `POST /environments/{name}/publish`: a Kubernetes Job (or CI, for the shared image) pushes the image
   to `settings.simulator_image_repository` under its hash and records an `oci` artifact with the registry's digest;
   the run path pulls an available `oci` artifact before building. The repository must be readable by the cluster
   (a public package, or credentials on the pull).

## Verification

- Unit tests per phase: the monitor's per-backend polling; artifact recording, adoption, verification; the Job's
  shape; a build run end to end against a fake Kubernetes (completed, failed, refused pod); a run joining an
  in-flight build; the build route.
- Live, after phase 3's release: rerun the Ciliberto comparison (comparison 1 failed on 2026-10-13). The first run's
  build is a Kubernetes Job; `environment_image` records the `.sif`; both runs complete; the comparison scores.
- After phase 4: `POST /environments/registry_env/build` on an already built environment answers its available
  image without starting a Job.

## Out of scope

Building prebuilt simulators' images (they are pulled by digest), garbage-collecting old images, multi-architecture
images, and per-tenant build quotas.
