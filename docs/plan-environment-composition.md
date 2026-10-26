# Composed environments: built by compose-api from curated entries, certified by compliance composites

**Status (2026-10-25): decided (Jim); step 0 in review.**
- One PR per step, each merged with a merge commit; each PR updates the table below.
- This plan supersedes the open parts of [plan-environment-versions](plan-environment-versions.md): step 5b's solver check, step 6, and the shared uv build path.
- The rest of that plan stays: versions as database records, defaults, retirement, read-back, every run recording its version, suites naming theirs, the admin role, and the prebuilt kind.

| Step | What | State |
|---|---|---|
| 0 | This document | in review |
| 1 | Manifest entries declare how they install; environments declare their member entries | |
| 2 | The runner (runtime contract 2), in place of pbest's | |
| 3 | pixi: generated from entries, locked in an unprivileged Job; the `composed` version kind | |
| 4 | Build, read back, record; export as pixi or uv | |
| 5 | Compliance: composites per entry, generic interface checks, levels computed per version | |
| 6 | registry_env migrates to a composed version on a current process-bigraph | |
| 7 | The per-composite resolver: mash-ups built on demand from a run | |
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
4. **Build, read back, record, export.**
   - Reuse the Kubernetes build Job and the read-back.
   - `POST …/versions` creates composed versions (admin), with the CLI to match.
   - `GET …/versions/{n}/export?format=pixi|uv`. The lock Job also resolves the uv form when the environment needs no conda.
5. **Compliance.**
   - `compose_api/registry/compliance/<entry>/` holds composites and expectations; the generic checks are shared.
   - When a version is ready, compose-api submits its members' compliance runs (label `source=compliance`), evaluates them, and stores each entry's level per version (a new `entry_level` table).
   - Admission (`validate_submission`) accepts an entry at `tested` in the version that will run.
6. **registry_env migrates.**
   - pbsim-common and biosim-toolkit move to process-bigraph ≥1.9.1. pbsim_common is changed only with Jim's go-ahead.
   - Create the first composed version, run Ciliberto and biomodels-curated-300 on it, and compare with run 3. Make it the default when it holds.
7. **The per-composite resolver.**
   - A document's addresses map to entries; then choose a covering ready version, or create and build a mash-up implicitly.
   - Validation is generalised beyond the registry_env bundle.
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
- **How a mash-up is named,** and when an implicit mash-up is garbage-collected.
- **Placement across islands when a composite cannot share one environment** (EV6–EV8, rule 3 of decision 5). It stays out of this round: a conflict is reported, not split.
