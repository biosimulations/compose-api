# Environment versions: locked, built and chosen through the API

**Status (2026-10-25): step 1 merged (#369); step 2 in review (#370).** One PR per step, merged with a merge commit; each PR updates the table below. A
merge deploys nothing by itself: the next release's image ships it (CLAUDE.md, "Deploys are GitOps").

| Step | What | State |
|---|---|---|
| 1 | This document | merged (#369) |
| 2 | `environment` and `environment_version` tables; today's two environments seeded as version 1 and made the defaults; one function chooses a run's version. No change in behavior | in review (#370) |
| 3 | A shared version is a **lock**: compiled by the API with uv, its hash the identity; the definition installs from it | |
| 4 | Creating versions through the API (refresh, prebuilt registration), with the lock diff, the installed packages and the interfaces recorded; the admin role | |
| 5 | Choosing them: `environment_version` on runs, required on suite runs; recorded on every simulation and suite run | |
| 6 | Retire the hard-coding: `PREBUILT_SIMULATORS`, `shared_image()`, the committed interface manifests | |

This is the first concrete step of the epoch-2 environments plan
([#317](https://github.com/biosimulations/compose-api/pull/317), `docs/plan-environments-epoch2.md`, proposed). It
takes **EV0**'s word (*environment version*, not *simulator*), a first form of **EV1** (identity is a lock hash,
compiled with uv until EV2's pixi workspace exists), and **EV12**'s registration and versioning. Publishing (epoch 1's
phase 5, EV12's push by digest) stays deferred.

## Why

libvcell 0.0.24 (2026-10-25) fixes `sbml_to_vcml` on SBML with a namespaced annotation, the cause of six vcell
failures in biomodels-curated-300 run 3. Production could not use it without a compose-api code change and a
release, though nothing in compose-api had changed:

- **The shared environment is compiled into the code.** `simulator_registry.json` and the pinned pbest produce one
  Apptainer definition, and its md5 is the environment's identity. Five places compute it (`handlers.run_simulation`,
  `builds.environment_definition`, `registry/environments.shared_image()`, `registry/generate.py`,
  `routers/simulations.py`).
- **A prebuilt environment is a deployment setting** (`PREBUILT_SIMULATORS` in `api.env`).
- **There is no other version to choose.** A run uses exactly the definition the running code generates. Building
  again does nothing: `POST /registry/environments/{name}/build` builds that same definition, and images are
  write-once (plan-environment-builds E4).
- **The identity does not describe the contents.** The definition pins top-level packages only
  (`pip install 'pyvcell[native,ode]==0.5.2'`); libvcell, numpy, process-bigraph and every other transitive package
  are resolved on the day of the build. So a transitive fix cannot arrive without editing the definition, an image
  rebuilt after a loss differs from the one it replaces, and CI's Docker build for the interface manifests can
  resolve differently from the cluster's SIF (EV1's complaint, met in practice).

**Outcome:**
- **An environment version is a database record**, created through the API: no PR, no release, no deploy.
- **Its identity is what it installs.** A refresh whose lock comes out the same is the same version.
- **Every run records its version**, and a suite run names its versions explicitly. A suite's environment is then
  independent of the compose-api release that invokes it.
- **Implicit builds stay** (strategy decision 5's per-composite resolver depends on them), gated by the registry, not
  by who asks.

## Decisions

| | Decision | Why |
|---|---|---|
| V1 | **An environment version is a database record**: environment, number (`registry_env@2`), state, its simulator row (definition text and hash, through which its images and builds already hang), and for a shared version its lock | the code stops deciding what runs; old versions stay runnable because their definition is stored, not regenerated |
| V2 | **A shared version's identity is the sha256 of its lock.** The API compiles it with uv (`uv pip compile --python-version 3.12 --python-platform x86_64-manylinux_2_28 --exclude-newer <resolved_at>`) over the spec (the libraries plus pbest at its tag) as one resolution; the definition installs from it with `uv pip sync`. Conda packages (readdy), apt and the base image still float; what was installed is recorded from the image | EV1 in its first form: deterministic PyPI contents, a diff before any build, and no new version when nothing changed. EV2's pixi workspace can replace the compiler later without changing the record |
| V3 | **A prebuilt version is an image by digest**, registered through the API | `PREBUILT_SIMULATORS` was a deployment-time version pointer; it becomes a record like the shared ones |
| V4 | **Each environment has a default version**, used only when a request names none (pbest, `/simulation/run`). A suite run always names its versions, and they are stored on it | reproducible suites and comparisons across versions (run 3 on @1 against run 4 on @2); old clients keep working |
| V5 | **The registry is the trust gate, not the caller** (below) | keeps implicit builds for the per-composite resolver; gates only what no review has seen |
| V6 | **A version records its runtime contract**: the interface between the job script and the image (pbest `main.py` arguments, the `PBG_*` variables). compose-api refuses a version whose contract it does not support | what makes "independent of the compose-api release" safe in both directions |
| V7 | **What a version provides is read from it, once, at build**: installed packages (`pip freeze`, `micromamba list`) and interfaces (`pbg-interfaces/1`, the pinned describe script) are written beside the image and stored on the version | the committed manifests describe the one image the code deploys; with many versions, each carries its own |

## Authorization

A build runs package code as root in the privileged build pod (plan-environment-builds E7); every run then runs that
code on HPC as the service user; a build costs about 20 GiB of scratch and minutes. Reviewed registry entries
(`manifest.yaml`, and `simulator_registry.json` for the shared bundle) carry the review, so the rule follows where a
version's inputs came from:

| Action | Inputs | Who |
|---|---|---|
| **Implicit build**: a run's version has no image yet (today's case), or, later, the per-composite resolver needs a spec with no ready version | registry-derived | **any submitter, anonymous included**, within the submission queue's caps (`submission_max_preparing`) |
| **Reuse**: a run naming no version gets the default; later, the resolver takes the newest ready version of the same spec | none | any submitter; the version is recorded on the run |
| **Refresh**: the same spec, resolved today (the libvcell case) | registry-derived, new transitive code | **admin** |
| **Custom libraries**, not derived from the registry (`origin = custom`) | unreviewed | **admin only, and only on the privileged builder.** Offering it to users needs an unprivileged builder (rootless Apptainer, or CI); out of scope |
| **Register a prebuilt image** (replaces the `api.env` PR) | an arbitrary image | **admin** |
| **Set the default; retire a version** | | **admin** |

*Admin* is a new setting, `environment_admin_role`, matched against `principal.roles`; the role must exist in the
Auth0 tenant (auth0-pulumi). Until it is set, the admin actions answer 403 and the service behaves as today.

## The model

```text
environment          name, kind (shared | prebuilt), python (entry command), default_version
environment_version  environment, number, state (resolving | building | ready | failed | retired),
                     simulator → definition, hash, images, build runs (epoch 1)
                     shared:   spec (libraries, pbest ref), origin (registry | custom), resolved_at,
                               lock (text), lock_sha256 (the identity)
                     prebuilt: image (ref@sha256)
                     installed (text), interfaces (pbg-interfaces/1), runtime_contract,
                     created_by, created_at, note
simulation           + environment_version   (and the label environment_version)
suite_run            + environment_versions  {environment: version}
```

## API

- `POST /registry/environments/{name}/versions` (admin)
  - **Shared**, body `{resolved_at?, libraries?, note?}`: compiles the lock (defaults: now, the repo's
    `simulator_registry.json`). An identical lock answers the existing version (200). Otherwise a new version, its
    build started through `handlers.ensure_image` (201). `?dry_run=true` answers the lock and its diff against the
    default without creating anything.
  - **Prebuilt**, body `{image: <ref@sha256>, note?}`: pulled through the existing pull path; a Kubernetes Job runs
    the image's `python` with the describe script.
- `GET /registry/environments/{name}/versions[/{n}]`: state, lock, installed packages, interfaces, and a package
  diff (`?against=<n>`).
- `PUT /registry/environments/{name}/default` and `POST …/versions/{n}/retire` (admin). A retired version refuses new
  runs; its images are kept (E4).
- The existing `…/build` and `…/images` act on the default version.
- **Runs:** `/simulation/run` and `/sedml/run` take an optional `environment_version` (`registry_env@2` or an id);
  `POST /suites/{name}/run` requires `environment_versions`. A SED-ML solver maps to its environment
  (`solvers.yaml`), then to the version named for it. Comparison pages show each member's version.
- **CLI** (every operation needs a command): `environments versions | create | default | retire`.

## Steps

2. **Tables and seed.** The tables and columns, one idempotent alembic revision
   (`tests/common/test_migrations.py`). One function, `environments.versions.version_for`, replaces the places that
   computed a run's definition (`handlers.run_simulation`, `builds.environment_definition`, the registry's
   environment routes). It returns the version of the deployment's own definition (the shared library list, or a
   prebuilt simulator's pin in `PREBUILT_SIMULATORS`), made the environment's default, so runs use the same images
   as today.
   *As built (#370):* there is no seed at startup. A version is created, as the next number, the first time a run
   (or an environment route) needs that definition, under a per-environment advisory lock. This has the same effect
   and also covers runs that never pass through the lifespan. A deploy that changes a pin adds a version, and a
   rollback makes the earlier version the default again. `shared_image()` and `registry/generate.py` still compute
   the shared image on their own, for the committed manifests, until step 6.
3. **The lock.** compose-api owns the definition template (moving it from pbest's `generate_container_def_file`, as
   strategy decision 1 absorbs pbest): base image, micromamba with the conda pins, then `uv pip sync` of the lock
   into the runtime environment. `compose_api/environments/lock.py` compiles; `definition.py` renders. Nothing
   changes until a version is created.
4. **Creating versions.** The routes and the admin role. The build Job's privileged container also runs
   `pip freeze`, `micromamba list` and the describe script with `apptainer exec` against the new SIF, and the copy
   container moves `<hash>.installed.txt` and `<hash>.interfaces.json` beside it; recording the image stores them
   on the version and marks it ready. The prebuilt describe Job. Client, spec, CLI.
5. **Choosing versions.** The run parameters, the suite requirement (`sedml-suites.yml` passes repository
   variables), the simulation column and label, `solvers.yaml` checked against the chosen version's interfaces, and
   the web app's environment page listing versions with their diffs.
6. **Retire the hard-coding.** `PREBUILT_SIMULATORS` (read once by the seed, then removed), `shared_image()`, the
   committed `registry/manifests/*.json` and `registry-manifests.yml` (tests use fixtures).
   `simulator_registry.json` stays as the default spec of new shared versions until EV0 retires the library list.

**First use, libvcell 0.0.24:** `POST /registry/environments/registry_env/versions?dry_run=true` (expect
`libvcell 0.0.23 → 0.0.24` in the diff), create `registry_env@2`, run the Ciliberto smoke suite and
biomodels-curated-300 on it, compare with run 3 on @1, then make @2 the default.

## Verification

- **Unit and database tests:**
  - the seed is idempotent and keeps today's hash;
  - the same spec and `resolved_at` give the same lock and the same version, and a later `resolved_at` with an
    unchanged lock answers the existing version;
  - creating a version joins an in-flight build;
  - the default is used only when a request names nothing;
  - a suite run without `environment_versions` answers 422;
  - a retired version, and an unsupported runtime contract, are refused;
  - a non-admin gets 403 on create, default and retire, while an anonymous run whose default image is missing still
    starts the implicit build;
  - a refresh never moves the default.
- **The build Job's shape:** the freeze and describe steps are in its script, and the copy container moves their
  files.
- **Live after step 4:**
  - registry_env@2's lock shows `libvcell==0.0.24`;
  - its interfaces equal @1's apart from package versions;
  - BIOMD0000000056 imports on it.
- **Live after step 5:**
  - the Ciliberto smoke suite, then biomodels-curated-300 on @2, with the six jsbml import failures of run 3 gone;
  - @2 made the default.

## Out of scope

Publishing images to a registry (EV12's push), the pixi workspace (EV2), the per-composite resolver (EV4), the
`simulator` → `environment` renames in the API (EV0 migration step 1 is partly this; the renames are their own PRs),
an unprivileged builder, and garbage-collecting old versions' images.
