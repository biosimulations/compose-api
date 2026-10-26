# Composed environments: built by compose-api from curated entries, certified by compliance composites

**Status (2026-10-26): the active plan. Steps 0–5 merged; step 6 finishing (registry_env@5, suite run 5); step 7's decisions confirmed (D7.1–D7.10); 7a next.**
- One PR per step, each merged with a merge commit; each PR updates the table below.
- This plan supersedes the open parts of [plan-environment-versions](plan-environment-versions.md): step 5b's solver check, step 6, and the shared uv build path.
- The rest of that plan stays: versions as database records, defaults, retirement, read-back, every run recording its version, suites naming theirs, the admin role, and the prebuilt kind.

| Step | What | State |
|---|---|---|
| 0 | This document | merged (#382) |
| 1 | Manifest entries declare how they install; environments declare their member entries | merged (#383) |
| 2 | The runner (runtime contract 2), in place of pbest's | merged (#384) |
| 3 | pixi: generated from entries, locked in an unprivileged Job; the definition that installs the lock | merged (#385) |
| 4a | Environments get a stable id; versions and suite runs refer to it, never to a name | merged (#386) |
| 4 | Composed versions: created `resolving`, locked in the background, built, read back; exported as pixi | merged (#387) |
| 4b | The uv export (`pyproject.toml` and `uv.lock`) for a composed version that needs no conda | merged (#388) |
| 5a | Compliance checks: the generic `step-outputs-replace` check, cases kept with an entry, their evaluation; pbsim-common's first cases | merged (#389) |
| 5b | Compliance runs: after a build, each member entry's cases run in the version; levels recorded per entry and version; API and CLI | merged (#390) |
| 5c | Admission by what the version certifies: a refused component, a failed entry, members only | merged (#391) |
| 6 | registry_env migrates to a composed version on a current process-bigraph | @4 (0.7.46) and @5 (0.7.50) ready; suite run 5 running; then the default |
| 7a | Runs name an environment or have one inferred; environments listed from the database | merged (#415, #416) |
| 7b | Implicit mash-ups, proven with viva-basic-processes | 7b-1 (the entry and its case, #417) and 7b-2 (runs in any composed environment) in review; then 7b-3 (implicit creation), 7b-4 (live) |
| 7c | viva-pde-particle as a composed entry: the PDE + particle + ODE mash-up | |
| 8 | Retire the shared uv path, `simulator_registry.json`, `shared_image()`, pbest in images, `PREBUILT_SIMULATORS`, the committed interface manifests | |

## Why (2026-10-25)

**The install list misrepresented what ran.**
- A refresh preview of registry_env, compared with @1's packages as read back from its image, showed the mismatch.
- `simulator_registry.json` pins tellurium 2.2.11.1 and python-copasi 4.46.300, but @1 ran 2.2.13.1 and 4.48.311. pbest's old definition had installed the pins, then let other packages' dependencies upgrade them.
- A refresh would have *downgraded* both and dropped h5py, sympy and others.
- The list never said why a package is there or what it provides. Its upstream, `biosimulations/registry`, has been archived (2026-10-25).

**pbest holds the engine back.**
- The image runs pbest's `main.py`, and pbest pins `process-bigraph==1.0.5` and `bigraph-schema==1.0.14` exactly.
- Every viva-\* repo needs process-bigraph ≥1.4 to ≥1.9.1, so nothing can be combined with registry_env.

**The environment versions work was a detour from the original plan.**
- Strategy decision 5 said: one locked environment per composite, built from curated, pinned entries; common combinations cached; conflicting components split across containers. registry_env was "the first bundle, and a stopgap".
- The epoch-2 plan ([#317](https://github.com/biosimulations/compose-api/pull/317), EV0–EV16) worked it out: pixi, islands, curation per island.
- [plan-environment-versions](plan-environment-versions.md) versioned the stopgap rather than building the resolver. Its version records, defaults and read-back stay useful.

**Only viva-pde-particle is environment-shaped today.**
- It has a `pixi.lock` covering conda and PyPI, a frozen build, and CI that runs compose-api's Apptainer contract before publishing.
- Its own runner (`compose_runner.py`) answers the same command line compose-api gives prebuilt images, without pbest.
- The other viva-\* repos are plain packages with loose floors, mostly unlocked. fenics and smoldyn need conda dolfinx, or a Smoldyn built from source, which pip cannot supply.

## Decisions (Jim, 2026-10-25)

- **C1. compose-api builds environments.**
  - Spreading runtime dependencies across several repos that must move in lockstep is the failure to avoid.
  - One builder means one solve per environment, and the lock is recorded on its version.
  - Owners' images by digest (the prebuilt kind) remain a second kind.
- **C2. An environment is pixi, generated from manifest entries.**
  - Each entry declares how it installs: a PyPI pin, or a git repository at a commit, with extras, plus any conda requirements (dolfinx, a C++ engine).
  - An environment is a set of entries. compose-api generates its `pixi.toml`, locks it and builds the image.
  - This is EV0 (the registry is the only input), EV1 (identity is the lock, then the digest) and EV2 (pixi; conda supplies anything that links MPI, PETSc, HDF5 or BLAS; PyPI supplies self-contained wheels).
- **C2a. pixi builds every image; uv is an export.**
  - There is one lock format, one template and one identity rule. pixi resolves PyPI packages with uv itself.
  - Every version publishes `pixi.toml` and `pixi.lock`.
  - A version with no conda requirements also offers a generated `pyproject.toml` and `uv.lock` for local `uv sync`. They are resolved with exact pins from its `pixi.lock`, and offered only if uv arrives at the identical set.
- **C3. Compliance tests live with the registry entry.**
  - **A component that fails a generic check is refused on its own** in that version (Jim, 2026-10-25), not its
    whole entry. The entry's level comes from its cases.
  - What is certified is the *process class* that wraps a library (`CopasiUTCStep`), not the library: COPASI's and tellurium's own suites test only themselves.
  - Each entry carries small composites (`.pbg`) with inputs, expected outputs and pass/fail criteria: tolerances, reference tables, invariants.
  - **Generic interface checks** apply to every component, for example: a step fired twice leaves its latest result (the overwrite bug of pbsim_common#21); its ports resolve.
  - A package's own unit tests are extra evidence, not required.
  - After each build, compose-api runs every member entry's composites on the new image and records the entry's level *for that version* (EV5). Levels are computed, not asserted.
- **C4. registry_env migrates first.**
  - No new version on the uv path: libvcell 0.0.24 arrives in registry_env's first composed version.
  - This needs pbsim-common and biosim-toolkit on process-bigraph ≥1.9.1 (EV3). pbest leaves the image.
- **C5. On-demand mash-ups, this round.**
  - A run whose composite uses entries from several environments is resolved to the set of entries it needs.
  - It reuses a ready version that covers them, or creates a mash-up named by its sorted entries and builds it implicitly. The inputs are registry-derived, so anyone may trigger it (V5 of plan-environment-versions), within the submission queue's caps.
  - A conflict (`pixi lock` refuses) is reported to the submitter with the packages that conflict.

### Identity: environments, versions, mash-ups (Jim, 2026-10-25)
- **An environment's identity is its database id.** Its name (`registry_env`) is what requests and pages use, and it
  may change; nothing stores it as a reference:
  - every version refers to its environment by `environment_id`;
  - a run records its `environment_version_id`;
  - a suite run stores the ids of the versions it ran in.
  `env@n` is accepted as input and resolved to ids when a run or suite run is recorded. A run's `environment_version`
  label is a snapshot of the name at run time, for search, not a reference. (PR "environment ids", before step 4.)
- **What a named environment's versions share** is its declared composition (its `entries`). They differ in pins and
  resolution date. A version is identified by its lock hash, then its image digest.
- **A mash-up is an environment of its own, whose identity is its exact set of entries.** Its name is derived from
  that set (`mash-<hash>`). Two mash-ups with different sets are different environments.
  - Giving one a curated name is a rename.
  - Adding an entry makes another environment, never a version of the same one.
  - Mash-ups are never versions of a named environment: version creation takes no `entries` override.

### Choosing an environment for a run (step 7, proposed 2026-10-25)
1. **A named environment, or a named version, is used as given.** It is refused (400, listing what is missing) if it
   lacks a component the document uses. Suite runs always name theirs.
2. **Otherwise the service infers what the run needs:** the document's addresses mapped to entries through their
   module roots, plus the libraries those entries `require` (a manifest field added in step 7).
3. **It reuses a ready environment that covers that set** (a superset will do): named environments before mash-ups,
   then the smallest set, then that environment's default version.
4. **If none covers it,** the service creates a mash-up of exactly that set and builds it implicitly, the run waiting
   in the queue. Every entry must be `tested` or higher.
5. **If the entries cannot share an environment,** the request is refused with a 409 and pixi's explanation.
6. **Every run records the version it got.** An inferred choice can change later; to reproduce a run, name that
   version.

### Step 7's decisions (Jim, 2026-10-26: D7.1–D7.10 confirmed as recommended)

**What exists today, which step 7 starts from:**
- A run names a prebuilt image (`simulator=`) or goes to `registry_env`, with an optional `environment_version=`. No
  request can name a composed environment other than `registry_env`.
- The environment list (`GET /registry/environments`, the webapp) comes from `environments.yaml`, not the database.
- Only three component entries can be composed and are `tested`: pbsim-common, pb-multiscale-actin and
  biosim-toolkit, all three already in `registry_env`. viva-pde-particle is a prebuilt image with no `install`; the 48
  catalog entries are `listed`. So inference alone would always choose `registry_env`, and a mash-up needs a new
  composable entry before one can be built at all.
- viva-pde-particle's image carries no pbsim-common: its 14 classes are all `viva_pde_particle.*`. A document putting a
  UTC step beside its PDE and particle processes is the motivating mash-up (7c).

**Decisions:**
- **D7.1 A run names its environment, or has one inferred.** `/simulation/run` takes `environment=<name>` beside
  `environment_version=<n>`. `simulator=` stays as an alias for a prebuilt environment for one release. With neither,
  the environment is inferred (D7.2–D7.4). SED-ML runs are unchanged: each solver names its environment in
  `solvers.yaml`, and suites name their versions.
- **D7.2 Inference maps addresses to entries.** Each address goes to the entry whose module root contains it (the
  longest root wins). A component entry may list the library entries it needs in a new `requires` field (pbsim-common:
  tellurium, python-copasi, pyvcell, libvcell), which join the set. An address under no entry is refused (400), as
  today. An entry with no `install` (a prebuilt image's) can only be served by its own environment: a document mixing
  it with other entries is refused (409, "<entry> cannot be composed yet").
- **D7.3 Reuse before build.** Among environments whose default version is ready and whose entries cover the set (a
  superset will do): named before mash-ups, then the fewest entries, then the name. The run takes that environment's
  default version, and admission uses that version's standing (step 5c), as now.
- **D7.4 A mash-up is created when nothing covers the set.** Every entry must be `tested` in the manifest. The lock
  runs while the request waits (about 15 s), so a conflict is a **409 with pixi's explanation** before anything is
  recorded. The build and the compliance runs follow in the background, and the run waits in the queue until the
  image is ready, as a run on a new version of `registry_env` would.
- **D7.5 Who may cause a mash-up build.** Only a signed-in caller, while anyone may *use* a mash-up that
  exists. A build runs registry code as root on the privileged builder for a few minutes, so an anonymous request
  should not be able to start one; C5 said anyone, so this narrows it. At most two implicit builds run at a time, and
  the same entry set is never built twice (the identity is the set).
- **D7.6 Naming.** `mash-<first 10 hex of sha256 of the sorted entry ids>`; the environment records its entries, and
  the pages show them. Giving one a curated name is a rename (an admin action).
- **D7.7 A mash-up's later versions.** Only its first version is created implicitly. After that it behaves like a
  named environment: an admin refreshes it with `environments create`, and runs keep taking its default until then.
  A manifest pin that moves therefore never triggers builds by itself.
- **D7.8 Garbage collection: none this round.** Each version records when a run last used it (`last_used_at`), and an
  admin retires what is idle. Automatic retirement waits for data on how many mash-ups appear.
- **D7.9 Environments are listed from the database.** `GET /registry/environments` returns every environment row, with
  `environments.yaml` adding what it knows about the declared ones (the Python command, the describe pin). A new kind,
  `mash-up`, sits beside `shared` and `prebuilt`. The webapp lists mash-ups in their own group, with their entries.
- **D7.10 Validation follows the chosen environment.** The `registry_env` bundle check (`SERVICE_BUNDLE`) is replaced
  by "the entry is a member of the environment the run will use"; admission by the version's standing is unchanged.

### What is a safe component
- An entry in `manifest.yaml`, pinned to a release or a commit, whose compliance composites pass **in the environment version that will run it**.
- A new pin starts again at `listed`. Being in an environment confers no level.
- Builds still run package code as root (the privileged Kubernetes builder), so only registry-derived entries are built implicitly. Anything else stays admin-only, as before.

## Steps

0. **This document.**
   - Pointers to it from plan-environment-versions, from strategy decision 5 and from the docs index.
1. **Entries declare how they install; environments declare their members.**
   - `manifest.yaml` entries gain `install`: `pypi` (name, version, extras) or `git` (url, commit, extras), plus `conda` (requirements).
   - Libraries that registry_env needs without providing process classes become entries of `kind: library`: pyvcell[native,ode], tellurium, python-copasi and readdy. Their pins are corrected to what @1 ran.
   - In `environments.yaml`, a composed environment lists its `entries`.
   - A loader with validation (unknown entries, a git source without a commit, duplicate packages) and tests. No change in behaviour.
2. **The runner, runtime contract 2.**
   - A module compose-api writes into every composed image. It answers `run <doc> -o <out> -n <interval>` and writes `results_<time>.pber`, process-bigraph events, and `artifact.written` events.
   - It is generalised from viva-pde-particle's `compose_runner.py`, which answers the command line compose-api already gives prebuilt images (`job_script.py`), so the job script needs no change.
   - Tested against a current process-bigraph with a small composite.
3. **pixi.**
   - Generate `pixi.toml` from an environment's entries: the common core (process-bigraph and bigraph-schema at releases), conda requirements, and PyPI or git dependencies.
   - Lock it in an **unprivileged** Kubernetes Job: the pixi image, no service-account token, nothing mounted but scratch. The lock comes back between log markers, as the inspection Job does (`build_k8s.inspection_job`, `read_inspection_log`). Dependency metadata, which can run package code, therefore never builds in the API pod.
   - A new version kind, `composed`: its spec is the entries, its lock is `pixi.lock` and its sha256.
   - The Apptainer definition bootstraps the pixi image, runs `pixi install --frozen`, then adds the runner and the runscript.
   *As built, 3 (2026-10-25):*
   - **Generation and definition:** `environments/pixi.py` makes `ComposedSpec.of(...)`, `pixi_toml(...)` and `composed_definition(...)`.
     - `exclude-newer` is the resolution date, to the second.
     - The common core and the pixi image, pinned by digest, live in `environments.yaml` under `composition`.
     - Entries declare `types`, the runner's type tables.
   - **Locking:** `build_k8s.lock_job` and `lock_composed` run in the generic unprivileged scratch Job (`_scratch_job`, now shared with the prebuilt inspection Job). A conflict comes back as pixi's own explanation (`LockFailedError`).
   - **Checked by hand in the real pixi image (Docker, linux/amd64, as the service user):**
     - registry_env's generated workspace locks: 2,782 lines, with process-bigraph 1.9.1, bigraph-schema 1.8.1, libvcell 0.0.24, pyvcell 0.5.2, tellurium 2.2.13.1, python-copasi 4.48.311, pbsim-common at `26fa156`, and readdy 2.0.13 from conda-forge.
     - `pixi install --frozen` installs that lock.
     - The runner then runs pbsim-common's `CopasiUTCStep` on process-bigraph 1.9.1 (phase_cycle, 11 points, `numeric_result` registered from pbsim-common's own table). This is an early sign for step 6.
   - **Two findings, now in the definition:**
     - `pixi install` needs the `git` executable for a git source, and the pixi image has none, so the definition installs it.
     - libroadrunner's wheel links `libpython3.12.so.1.0`, which conda-forge ships in the environment's `lib` with no rpath to it. The definition therefore puts that directory on `LD_LIBRARY_PATH`.
4. **Build, read back, record, export.**
   - Reuse the Kubernetes build Job and the read-back.
   - `POST …/versions` creates composed versions (admin), with the CLI to match.
   - `GET …/versions/{n}/export?format=pixi|uv`. The lock Job also resolves the uv form when the environment needs no conda.
   *As built, 4 (2026-10-25):*
   - **Which environments are composed:** an environment that lists `entries` in `environments.yaml`; registry_env
     now does.
   - **Creating a version** (`POST …/versions`, admin) records it at once, `resolving`. It records the spec: entries,
     core, `pixi_toml`, `pixi_image`, runner types. It has no simulator yet: `simulator_id` is nullable and the
     version gains `failure`; migration `b6d1e8f2c473`.
   - **In the background:** the lock Job runs, then the definition is made and the version gets its simulator and
     becomes `building`, then the existing build and read-back run.
   - **A version that does not resolve** is `failed`, with pixi's explanation in `failure`.
   - **A version that resolves to a lock another version already has** is `failed`, naming that version. It is caught
     by lock hash, since two dates that lock alike still differ in the workspace's `exclude-newer`.
   - **Refused for a composed environment** with a 422: `libraries`, `image`, and the preview. The preview gives way
     to comparing versions once they resolve.
   - **The read-back** enters a composed image through pixi's activation (`pixi.PYTHON`), whatever the environment's
     older versions used.
   - **Export:** `GET …/versions/{n}/export?format=pixi|requirements` is public and returns the files. CLI:
     `environments export NAME N [--out DIR]`, which writes file names only, into `--out`.
   - **Deferred to 4b:** the uv form, which needs uv in the lock Job.
   *As built, 4b (2026-10-25):*
   - **When:** after a composed version resolves and builds, if its entries need nothing from conda-forge.
   - **The project** (`environments/uv_export.py`): a `pyproject.toml` naming the entries and core as dependencies
     and constraining every other PyPI package to the version in `pixi.lock`. It is `package = false`, with the same
     `exclude-newer`.
   - **Locking:** uv locks it in the same unprivileged scratch Job (`pixi exec --spec uv uv lock`).
   - **Kept only if identical:** the form is kept only when uv's packages and versions equal pixi's, and is served
     as `export?format=uv`.
   - **Platform:** the project is restricted to `sys_platform == 'linux' and platform_machine == 'x86_64' and
     implementation_name == 'cpython'`, what pixi locked for and the image runs. Without the CPython clause, uv
     added `cffi` and `pycparser`, which are PyPy-only dependencies.
   - **Checked in the real pixi image:** registry_env without readdy and pb-multiscale-actin locks to the same 89
     packages, at the same versions, under pixi and uv.
5. **Compliance.**
   - `compose_api/registry/compliance/<entry>/` holds composites and expectations; the generic checks are shared.
   - When a version is ready, compose-api submits its members' compliance runs (label `source=compliance`), evaluates them, and stores each entry's level per version (a new `entry_level` table).
   - Admission (`validate_submission`) accepts an entry at `tested` in the version that will run.
   *As built, 5a (2026-10-25):*
   - **The generic check** (`environments/compliance.py`), `step-outputs-replace`, works from a version's interfaces
     and its entries' type tables, with no run. A step whose output ports would *add* (`float`, `integer`, `array`)
     or *append* (`list`) its result into the store, instead of replacing it, fails, with the paths that accumulate.
     Processes are exempt: their updates are changes over an interval.
   - **On today's registry_env it fails:**
     - pbsim-common's three time-course steps and `TelluriumSteadyStateStep`, which pbsim_common#21 fixes;
     - `ComparisonTool`, `MSEComparison`, `StatsTool` and `SumOfSquaresTool`, the same bug, which #21 does not cover
       yet.

     biosim-toolkit's steps already overwrite.
   - **Cases** (`registry/compliance/<entry>/<case>/case.yaml`, with the document and the files it reads) expect
     `rows`, a `value` at a time, or agreement with a `reference` CSV.
   - **pbsim-common's first two cases:** `CopasiUTCStep` and `TelluriumUTCStep` on the public phase-cycle model,
     against COPASI's own report at t = 0, 2, …, 10. Both passed in the real pixi image on process-bigraph 1.9.1, run
     by the runner from an omex as step 5b will.
5b. **Compliance runs.**
   *As built (2026-10-25):*
   - **When:** once a composed version is ready and read back, `compliance_runs.start` submits each member entry's
     cases through the run path.
   - **What a case run is:** an omex of the case's document and files, run in *that* version (`environment_version`
     is its number), queued as `compliance:<environment>`, labelled `source=compliance` and
     `compliance=<entry>/<case>`.
   - **Where it is recorded:** in `compliance_run`, one row per version, entry and case.
   - **Evaluation** happens when the report is read (`GET …/versions/{n}/compliance`, public), so nothing polls:
     - a finished run's `.pber` is read from its experiment directory and checked against the case;
     - a run that did not complete is an `error`.
   - **An entry's level:**
     - `tested` when all its cases passed;
     - `pending` while any runs;
     - `failed` when one did not pass;
     - `untested` without cases.
   - **The generic checks** run at read-back. The read-back now also prints the image's type tables (`types.json`,
     from `COMPOSE_RUNNER_TYPES`), and their findings are kept on the version (`findings`, migration
     `e5a8b3d1f926`). The report lists the refused components.
   - **Running them again:** `POST …/compliance` (admin) runs a ready composed version's cases again. The client
     sends it once and never retries it, since it submits runs.
   - **CLI:** `environments compliance NAME N [--run]`.
   - **A bug the tests caught:** the type-table script was first called `types.py`, which shadowed Python's `types`
     module for the describe script beside it. It is `type_tables.py`.
5c. **Admission by what the version certifies.**
   *As built (2026-10-26):*
   - **The standing** (`environments/admission.py`): `standing_for(environment, number)` gives the standing of the
     version a run will use, the named one or the default. It holds:
     - its members, for a composed version;
     - each entry's level, from its case runs as recorded;
     - the components a generic check refused there.
   - **Who passes it:** `/simulation/run` (registry path) and SED-ML submissions, per solver environment. Without a
     database there is no version, and the manifest alone decides.
   - **The order** (`registry/validation.py`, `_registry_reason`):
     1. a component refused in the version is refused alone, with the check's detail;
     2. a composed version runs only its own entries;
     3. an entry that **failed** its cases there is refused;
     4. one that **passed** them (`tested`) is admitted, whatever the manifest asserts;
     5. one with cases `pending`, or no cases yet, keeps the manifest's level, as today.
   - **What changes in production now:** nothing. registry_env's default is @1, which is not composed and has no
     findings or case runs. The standing starts to decide when a composed version is the default (step 6), or is
     named.
6. **registry_env migrates.**
   *Live, 2026-10-26 (0.7.43–0.7.46):*
   - **registry_env@2:** the lock Job worked on the cluster at once (15 s, a 124 KB `pixi.lock`), but the build Job
     could not start. Its definition, passed in one environment variable, exceeded Linux's 128 KiB limit
     (`argument list too long`). Fixed in #394 by gzipping the definition.
   - **@3:** a failed version's lock could not be made again; fixed in #396. Then Apptainer refused @3's
     definition: each section is read as one token of at most 64 KiB, and `%post` held the lock. Fixed (0.7.46):
     - the definition copies `pixi.toml`, `pixi.lock` and the runner in through `%files`, and records their sha256
       as labels, so its hash still follows them;
     - the build Job carries the files as a gzipped tar, in chunks of under 96 KiB;
     - a version records its runner's source when it is created, and is rebuilt with it;
     - `%runscript` runs under `/bin/sh`, which has no `source`, so it hands pixi's activation to bash.
   - **Checked before release, with real Apptainer 1.3.6 in Docker:** the build Job's own script built registry_env
     from its real lock into a 480 MB SIF (@1's is 1.0 GB), with the labels. `apptainer run --compat` with
     `/experiment` bound then ran the COPASI compliance case through the runner, and it passed.
   - pbsim-common and biosim-toolkit move to process-bigraph ≥1.9.1. pbsim_common is changed only with Jim's go-ahead.
   - Create the first composed version, run Ciliberto and biomodels-curated-300 on it, and compare with run 3. Make it the default when it holds.
7. **The per-composite resolver**, in three parts (D7.1–D7.10).
   - **7a. Naming, inferring, listing; no new builds.**
     - `environment=` on `/simulation/run` (D7.1), with the client and CLI options.
     - The resolver: addresses to entries, `requires` in the manifest (pbsim-common's libraries), and choosing a
       covering ready environment (D7.2, D7.3). With today's entries it always chooses `registry_env`, so no run
       changes; a test pins that.
     - Environments listed from the database, the `mash-up` kind, and `last_used_at` (D7.8, D7.9).
     - Validation by membership of the chosen environment (D7.10).

     *As built, 7a-1 (2026-10-26, #415):*
     - `requires` on manifest entries (pbsim-common: tellurium, python-copasi, pyvcell, libvcell), checked to name
       existing entries; an environment must list what its entries require (`spec_problems`).
     - `registry/resolver.py`: `needed_entries` (addresses to entries by module root, with what they require) and
       `choose_environment`. The shared environment wins whenever it covers the set; then the smallest offered
       environment. A set none covers falls back to the shared environment, whose validation names what is missing,
       until 7b builds mash-ups.
     - `/simulation/run`: `environment=<name>` (any offered environment; `simulator=` agreeing with it or omitted).
       A run naming no environment, no simulator and no version is inferred. `environment_version` alone still means
       the shared environment's version, as before.
     - Validation checks membership of the chosen environment (`environment=` on `find_violations` and
       `validate_submission`; the message names it).
     - Client `submit(environment=)` and CLI `run --environment`.
     - The one behaviour change: a document using only viva-pde-particle's classes, sent with no `simulator`, now runs
       in its image when the deployment offers it, instead of being refused. A test pins that every class
       registry_env provides is still inferred to registry_env.

     *As built, 7a-2 (2026-10-26):*
     - `environment.entries` (JSONB, migration `f6b2c9d4e017`) holds a mash-up's sorted entries, its identity; the
       `mash-up` kind sits beside `shared` and `prebuilt`. Declared environments keep their entries in
       environments.yaml.
     - `GET /registry/environments` lists the declared environments, then the database's mash-ups, each summarized
       from its default version (the classes its image read back, its core). The read-only version routes (list,
       one version, export, compliance) accept a mash-up's name; creating versions of one waits for 7b.
     - `last_used_at` on every version (D7.8) is read from its newest simulation, not written by each run.
     - The webapp lists mash-ups with their entries and an `info` badge; their page has no committed manifest or
       deployment image, and their classes are on each version's page.
   - **7b. Implicit mash-ups, proven with a light component.**
     - Creation when nothing covers the set: the lock in the request (409 on a conflict), the build and compliance in
       the background, the run queued behind the image (D7.4–D7.6). Signed-in only, two builds at a time (D7.5).
     - The first real member (Jim, 2026-10-26): **viva-basic-processes**, pinned by commit (`9a1a624`; it is not on
       PyPI, and its `v0.3.0` tag predates the rename and installs as `pbg-basic-processes`). Its dependencies are
       process-bigraph ≥1.4.12, bigraph-schema, sympy and numpy; on our core (process-bigraph 1.9.1, bigraph-schema
       1.8.1) it installs and provides `Clock`, `Tick`, `Intervention` (processes) and `MathExpressionStep` (a step),
       checked 2026-10-26. Raised to a manifest entry with an `install` pin and a compliance case, at `tested`.
     - Why it: its classes exchange state with an ODE, so a mash-up tests that two entries' ports fit, not only that
       they install together. The document: pbsim-common's `CopasiUTCProcess` steps an ODE, `Intervention` changes a
       species partway through, `MathExpressionStep` derives a readout; its compliance case checks the step change.
     - *As built, 7b-1 (2026-10-26):* the manifest entry (git `9a1a624`, `tested`, in no declared environment) and
       its compliance case `intervention-and-expression`: Intervention adds 2 per step to x (from 1), MathExpressionStep
       writes y = 3x + 1, Clock ticks; after five steps x = 11, y = 34, tick = 5, and x = 5 after two. Run locally through
       compose-api's runner on process-bigraph 1.9.1, the case passed. Compliance gains a `scalar` expectation (a
       plain number in an emitted row), since these stores are floats, not a `numeric_result`.
     - *As built, 7b-2 (2026-10-26):* a run can name a composed environment the deployment does not declare.
       `SimulationRequest.environment` carries a mash-up's name, and `version_for` takes its named version or its
       default from the database (`composed_version`; there is no deployed definition to adopt). `/simulation/run`'s
       `environment=` accepts a mash-up the database holds (`simulator=` with it is a 400). Admission uses that
       version's standing, so its members are admitted and anything else is refused, and the run is labelled with it.
       A version's compliance cases now name its environment, so a mash-up's run in the mash-up (before, they would
       have run in registry_env). Mash-ups are still made only directly; 7b-3 makes them from a run.
     - Second, later: viva-emitters (PyPI 0.4.3; `SQLiteEmitter` needs no extras). viva-torch is too heavy for a first
       test. Pinning viva-basic-processes changes nothing in vivarium-collective.
     - Live: a document using it with a pbsim-common step creates `mash-…`, builds it, runs, and a second identical
       run reuses it. A deliberately conflicting pair answers 409.
     - The webapp shows mash-ups on the environments page.
   - **7c. viva-pde-particle as a composed entry: the PDE + particle + ODE mash-up.** Two things block it today:
     - **Smoldyn is not a package.** viva-pde-particle compiles it from a patched submodule while its image builds
       (`build-smoldyn`). Either manifest entries gain a reviewed `build` step, run in the build Job after `pixi
       install`, or Smoldyn is published as a package (conda-forge or a wheel). To decide with Jim.
     - **Some of its dependencies track `main` branches** (viva-superpowers, viva-workspace, viva-catalog); C2 needs a
       release or a commit for each.
     - Both are changes in vivarium-collective, made only with Jim's go-ahead. Then: an `install` and `conda` for the
       entry (fenics-dolfinx 0.10, MPI, Netgen), compliance cases kept with it, and a document combining its
       processes with `VCellUTCStep` or `CopasiUTCStep`, built as a mash-up.
8. **Retire:**
   - the shared uv path;
   - `simulator_registry.json`;
   - `shared_image()`;
   - pbest inside images. Its HTTP-client role, and the `operation_id`s it relies on, are unaffected.
   - `PREBUILT_SIMULATORS`;
   - the committed `registry/manifests/*.json` and `registry-manifests.yml`.

## Verification

- **Unit tests:**
  - generating pixi from entries;
  - the lock Job's shape and the parsing of its log;
  - the runner on a small composite;
  - evaluating compliance (pass, fail, tolerance);
  - the resolver choosing a covering version or creating a mash-up;
  - a lock conflict reported as a 409.
- **Live:**
  - A composed registry_env version builds. Its read-back lists `libvcell==0.0.24` and process-bigraph ≥1.9.1, and compliance records `tested`.
  - Ciliberto and the 300-model suite run on it.
  - A mash-up, for example viva-emitters with registry_env's entries, is built implicitly from a run.

## Open questions

- **Where the pixi image and the builder's pixi version are pinned.** Probably beside the describe pin in `environments.yaml`.
- ~~How a mash-up is named, and when an implicit mash-up is garbage-collected.~~ Proposed as D7.6 and D7.8.
- **Placement across islands when a composite cannot share one environment** (EV6–EV8, rule 3 of decision 5). It stays out of this round: a conflict is reported, not split.
