# Plan: VCell's ODE solver as a SED-ML time-course solver

## Goal
- Run SBML time courses on VCell's Sundials solvers, through pyvcell, as a third solver beside COPASI and Tellurium.
  It should be usable in `/sedml/run`, in suites and in comparisons.
- pyvcell 0.5.0 (`simulate_ode`) and libvcell 0.0.23 make this possible:
  - libvcell 0.0.23 writes the solver input and bundles BioNetGen;
  - pyvcell-odesolver 0.9.7 solves it, and its Linux wheels now load on a stock Linux.
- **Out of scope:** spatial solvers (finite volume, moving boundary) and VCML-native processes. They return fields,
  not time courses, and belong in their own package and image later. vcell-fenics stays out as well.

## Decisions (2026-10-24)
| | Decision | Why |
|---|---|---|
| V1 | **`VCellUTCStep` lives in pbsim_common**, next to `CopasiUTCStep` and `TelluriumUTCStep` | Same contract and same role (TimeCourseSolver); the repository is ours (biosimulations) |
| V2 | **It runs in `registry_env`** | The image runs Python 3.12, which pyvcell needs; pyvcell and its native extras ship manylinux wheels |
| V3 | **SBML whose units are undefined is read with `assume_units="sbml_l2"`** | SBML Level 2's defaults, filling in only what is undefined; this matches COPASI's reading of the same file |
| V4 | **No unit conversion** (`unit_system=None`) | Results come back in the model's own units, so they line up with COPASI's and Tellurium's |
| V5 | **pyvcell is an optional extra of pbsim-common** (`pbsim-common[vcell]`) | libvcell is about 100 MB; other pbsim-common users should not pay for it |

## The step (pbsim_common)
`pbsim_common/simulators/vcell_process.py`, class `VCellUTCStep(Step)`.

**Contract.** The config schema, inputs and outputs are the same as `CopasiUTCStep`'s, so the SED-ML translator fills
it the same way:
- config: `model_source` (an SBML path), `time`, `n_points`, `output_dir`;
- output: `result: numeric_result`, with `time`, `columns` and `values`;
- `results.csv` is written to `output_dir` when it is set.

**`initialize`:**
1. Load the model with `pyvcell.vcml.load_sbml_file(model_source, assume_units="sbml_l2")`. pyvcell's own
   "`assume_units` refuses a model that declares some of its units" applies only to `"vcell"`. `"sbml_l2"` fills in
   just the undefined ones.
2. Find the single non-spatial application, and add an ODE simulation:
   `add_ode_sim(duration=time, output_times=linspace(0, time, n_points))`.
   - Output times are given explicitly, not as a step, so there are exactly `n_points` rows at the same times as
     COPASI's. Floating-point drift in `output_time_step` could otherwise add or drop the last point.
   - The solver is VCell's Combined solver: CVODE, or IDA when the model has fast systems or algebraic rules.

**`update`:**
1. Apply incoming species values to the initial conditions, as COPASI's step does.
2. Call `simulate_ode`.
3. Return the result with columns named by **SBML id**.

**Errors.** A model VCell can't import, or a solve that fails, raises with libvcell's message. A suite records
those through its `expected` list as solver limits, as it does for Tellurium's delay equations.

**Tests** (pbsim_common CI, Linux and macOS):
- the phase-cycle fixture already used for COPASI and Tellurium: VCell's result agrees with COPASI's within the
  suite's tolerances;
- a unitless SBML Level 3 model, so `sbml_l2` is applied;
- `n_points` rows exactly;
- columns by SBML id.

## Wiring into compose-api
1. **pbsim_common:** add the step, the `vcell` extra (`pyvcell[native,ode]>=0.5.0`) and the tests. Merge; the
   version becomes `0.1.3.dev1`. It is still installed from git until 0.1.3 is on PyPI (PyPI ownership is pending).
2. **pbest:** move its pbsim-common git pin to that commit and tag `0.6.5`. The container definition clones pbest's
   tag and installs pbsim-common through pbest's requirements, *after* the image's libraries. A newer pbsim-common
   therefore reaches `registry_env` only through a pbest tag.
3. **compose-api,** in one PR:
   - **`simulator_registry.json`:** add `pyvcell[native,ode]` at 0.5.0 (PyPI). This installs pyvcell in the image
     only, not for pbest's other users.
   - **The pbest pin:** move `pbest==0.6.4` to 0.6.5, plus the `[tool.uv.sources]` tag. Together with the library
     entry, this changes the definition's md5, so the next run rebuilds the image.
   - **`registry/manifest.yaml`:** pbsim-common's `source` and `version` move to the new commit; no new entry,
     since `pbsim_common` is already a module root.
   - **`registry/solvers.yaml`:** add an entry, in `registry_env`, with `provides: [species]`:

     ```yaml
     id: vcell
     name: VCell (CVODE/IDA)
     address: local:pbsim_common.simulators.vcell_process.VCellUTCStep
     algorithms: ["KISAO:0000019", "KISAO:0000283"]
     ```

     `tests/registry/test_solvers.py` requires the class in `registry_env`'s committed manifest.
   - **`registry/manifests/registry_env.json`:** regenerate it with `registry-manifests.yml`, the CI workflow, which
     runs the describe script in the built image and opens a PR.
   - **`tests/simulators/test_vcell.py`:** follows `test_copasi.py` (`slurm`, `cluster_only`). It runs the
     phase-cycle archive on `vcell` inside the built image.
   - **`/sedml/run` with no `solvers` runs every solver**, so `vcell` joins the default set. The translator refuses
     it for a task whose algorithm it doesn't implement, as it does for the others. An interactive archive therefore
     gets a third run by default.
   - **Suites name their solvers explicitly,** so none grows a third run until its `suite.yaml` adds `vcell`.

## Verification
- **pbsim_common CI:** the tests above.
- **compose-api:** `make check`, `make test`, and the cluster test on the deployed image.
- **Fidelity at scale:**
  1. Run `biomodels-curated-300` with `solvers: [copasi, tellurium, vcell]`.
  2. Record where VCell disagrees, or can't import a model, in the suite's `expected` list, with reasons.
  3. Fix adapter bugs in pbsim_common, as was done for COPASI and Tellurium (pbsim_common#18).
- **Against VCell itself:** the verify oracle (`docs/plan-verify-oracle.md`) compares runs with legacy VCell runs.
  A `vcell` member should match the oracle more closely than the other solvers, which is a check on the step itself.

## Risks and open questions
- **Species names.** VCell's SBML import can rename ids, for example reserved words, or a species that appears in
  more than one compartment.
  - The step must map VCell's variable names back to SBML ids before returning, since comparisons match columns by
    name.
  - If libvcell doesn't record the mapping, the first suite run shows how often this happens, and the fallback is a
    small id map built at import.
- **Amounts vs concentrations.** Species with `hasOnlySubstanceUnits` must come back in the same quantity COPASI
  reports. The step's tests include such a species.
- **SBML features.** VCell may refuse some features that COPASI accepts (for example certain event or delay
  constructs). Those become expected solver limits, not adapter bugs.
- **Tolerances.** The step uses VCell's defaults unless the SED-ML gives KiSAO parameters. Mapping those parameters
  (absolute/relative tolerance, maximum step) is a follow-up, shared with the oscillator tolerance issue (BIOMD43).
- **Rule-based models.** They aren't an issue for SBML input. VCML or BNGL input later would need a full Perl in the
  image for BioNetGen; the image's bookworm base has only `perl-base`, without `FindBin`.
- **The pin chain.** Steps 1 and 2 stay git pins until Ezequiel moves the PyPI ownership of pbsim-common and pbest.
  After that they become PyPI releases (pbsim-common 0.1.3 or later, pbest 0.6.5 or later), and the git sources go.

## Steps (one PR each, merge commits)
1. pbsim_common: `VCellUTCStep`, the `vcell` extra and tests; version 0.1.3.dev1.
2. pbest: the pbsim-common pin, then tag 0.6.5.
3. compose-api: the library entry, the pbest pin, the manifest, `solvers.yaml`, the cluster test; then regenerate
   `registry_env`'s interface manifest (CI PR); release.
4. Suite: add `vcell` to `biomodels-curated-300`, run it, and record the expected entries. The suite names `vcell`
   from 0.7.40; its run 3 is the first with it.
