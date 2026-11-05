# A suite from the SBML Test Suite: every ODE solver against the community's expected results

**Status (2026-11-05): plan merged (#515); step 2 merged (#516); step 3 merged (#517); step 4a merged (#518), live in 0.7.81; run 1 done, its baseline held back for the platform fixes (step 4c); S8–S11 decided by Jim. Not yet the active plan** ([README](README.md): entry-updates is).
One PR per step, each merged with a merge commit.

The suites we have (`examples/*/suite.yaml`; [plan-sedml](plan-sedml.md), phase 6) take models from BioModels and
biosimulations.org and compare the solvers with each other and with a reference that is not an arbiter (plan-sedml
D7). The [SBML Test Suite](https://github.com/sbmlteam/sbml-test-suite) is the opposite: small models, each written to
exercise one SBML feature, with expected results that are the answer. It tells us, feature by feature, what each
solver path (SBML → SED-ML → process-bigraph-lang → COPASI / Tellurium / VCell) gets right.

## Findings (2026-11-05)

1. **Release 3.5.0** (2025-07-14) is the newest. Its semantic archive, `semantic_tests_v3.5.0.zip`, has sha256
   `523bed25…eacea77` and holds **1823 cases**.
   - 1790 are `TimeCourse` and 34 are `FluxBalanceSteadyState`. The stochastic and syntactic archives are separate,
     and out of scope here.
   - 125 cases use `comp` and 34 use `fbc`; the other 1664 are core SBML.
2. **A case** (`cases/semantic/NNNNN/`) has the model at every SBML level and version it can be written in
   (`-sbml-l1v2.xml` … `-sbml-l3v2.xml`), plus three more files:
   - `-settings.txt`: `start`, `duration`, `steps`, the `variables` to report, `absolute` and `relative` tolerances,
     and which variables are reported as `amount` or as `concentration`;
   - `-results.csv`: the expected values at those `steps + 1` uniform times;
   - `-model.m`: `componentTags`, `testTags`, `testType`, `levels`, `generatedBy` (Analytic or Numeric), and a synopsis.
3. **There is no SED-ML in 3.5.0.** Release 3.4.0 had a `semantic_tests_with_sedml_and_graphs` variant; 3.5.0 does
   not. Our runs need a SED-ML document (a uniform time course plus a report of the variables), so the source has to
   write one from `-settings.txt`, which is a small, fixed transformation.
4. **A case's pass criterion is its own:** `|actual − expected| ≤ absolute + relative · |expected|`, with that case's
   tolerances. A suite has one `tolerances` setting for every source (`sedml/models.py` `Tolerances`), so this suite
   needs tolerances per source.
5. **Amount or concentration is per variable.** A reported species is an amount or a concentration as the settings
   say, whatever its `hasOnlySubstanceUnits`. The SED-ML we write must ask for exactly that. A data generator that
   divides by the compartment's size is the usual way, and a wrong choice here shows up as a solver failure that
   isn't one.
6. **The tags are the point.** There are about 100 component and test tags, for example `EventWithDelay` (≈230),
   `AlgebraicRule` (≈125), `CSymbolDelay` (54), `FastReaction` (≈35) and `comp:*`. A result read by tag (per
   solver: passed, failed, couldn't translate) is what makes this suite worth more than its pass count.
7. **Sources today are `biomodels:<id>` or `biosimulations:<project>`** (`Suite._sources`, `suite_runs._submit_source`).
   A third kind needs fetching, caching, a reference and a translation path, each in the same place those two have
   them.
8. **Licence.** The repository is "NOASSERTION" on GitHub; `LICENSE.txt` says most of it is jointly copyrighted by the
   SBML Team's institutions. We should fetch the release at run time, as we do BioModels, and not commit the cases.

### Found in step 2 (2026-11-05)

9. **process-bigraph-lang translates only linear data generators** (`x`, `2*x`, `x+y`; finding code X400). An
   amount made from a concentration is therefore `size * x` with the compartment's size as a number, which needs a
   size fixed in the model: constant, set, and not changed by a rule or an initial assignment.
10. **Of the 1790 time courses, 1621 (91%) can be written today.** The other 169 fail at the source, with the reason
    recorded on the suite row, so none is dropped (S6):
    - 89 ask for an amount or a concentration of a species whose compartment's size varies or isn't set (finding 9;
      for example 00027, 00051). They need a product of two variables in a data generator, which is a
      process-bigraph-lang change.
    - 79 `comp` cases report a submodel's element by its flattened id (`submod1__subparam2`, for example 01126). The
      model as written (S11) has no element with that id, and SED-ML has no standard way to address one inside a
      submodel instance. They stay recorded failures (S12).
11. **A sample of 50 writable cases (random, seed 7) translates for all three solvers** with the report the reference
    expects (`simulation.sedml/report`, labelled `time` and the variables). Translating a case takes about a second.

### Found in step 4 (2026-11-05)

12. **The tags are fewer than finding 6 counted:** 64 distinct component and test tags over the 1789 time courses
    that read. One case per tag needs only 14 cases, too few to say much. Covering every tag *and every pair of tags
    found together* (1261 pairs) needs 146, of which 21 cannot be written yet (finding 10); that is the sample. Only
    `comp:SubmodelOutput` is reached through unwritable cases alone.

### Found in run 1 of the sample (2026-11-05, 0.7.81, registry_env@5)

13. **Run 1 passed few cases, and most failures are ours, not the solvers'.** Of 125 cases run, COPASI passed 26,
    Tellurium 31 and VCell 5; 4 passed on all three. VCell's run failed in 96, Tellurium's in 50, COPASI's in 5. The
    causes, platform first:
    - **The archive left out external models.** Ten `comp` cases (four in the sample: 01471, 01475–01477) define a
      submodel in another file of the case (`external-l3v2.xml`), named relative to the model. Without it no solver
      could load them.
    - **Only species are reported.** Every solver in `solvers.yaml` says `provides: [species]`, so the translator
      leaves out a parameter or compartment that varies in time (X404), and the solver lacks the column: COPASI's
      "missing" in 68 cases.
    - **Species are reported as concentrations, always.** SED-ML reads a species with `hasOnlySubstanceUnits` as an
      amount; the solver steps return its concentration. 01307, 01455 and 01747: all three solvers agree, all wrong.
    - **VCell's SBML import refuses many features** (its run failures by cause): algebraic rules 21, `delay` 13, the
      `rateOf` csymbol 13, 0-D compartments 10, non-numeric or non-integer stoichiometry 10, no ODEs at all (rules
      and events only) 9, elements with no math 8, and 12 single causes. None is the solver: every case is
      non-spatial (no 3.5.0 model uses the `spatial` package), so `pyvcell.simulate_ode` is the right path; the
      import (vcell-core's `SBMLImporter`, through libvcell) fails before it.
    - **The solvers' own limits:** Tellurium cannot load the algebraic-rule models; COPASI is off in all 12
      `FastReaction` cases and in some `StoichiometryMath` ones, and crashed twice (01284, 01288).

## Decisions (proposed)

- **S1. A new source kind, `sbml-test-suite:<release>/<case>`** (for example `sbml-test-suite:3.5.0/00001`). The
  release is part of the source, so a comparison's `source` says exactly which case it ran. Each release a source may
  name is pinned by its archive's sha256 in `RELEASES` (`sedml/sbml_test_suite.py`), so a new release is a code
  change. (The draft put the pin in the suite's yaml; step 2 moved it into the source and the code.) The archive is
  fetched once, checked against the hash, and cached like a BioModels archive (`sources._cache`).
- **S2. The source writes its own OMEX:**
  - the model at its highest level (`l3v2`, else the highest it has);
  - a SED-ML document with one uniform time course (`start`, `duration`, `steps`) and one report of the settings'
    `variables`, each an amount or a concentration as the settings say (finding 5).

  The writer is a pure function with tests per case shape. It lives in compose-api, not in process-bigraph-lang,
  since it is about this suite's files.
- **S3. The expected results are a reference that is an arbiter.** `-results.csv` becomes the reference
  `sbml-test-suite:<release>:<analytic|numeric>` (S10). A solver passes a case when it is close to that reference within the case's own tolerances
  (finding 4). Agreement between solvers is still shown, but it doesn't decide.
- **S4. Tolerances per source.** A source can carry its own `Tolerances`, which win over the suite's. That is the
  smallest change that holds S3, and it may help other suites too.
- **S5. The suite starts small.** A first suite, `sbml-test-suite-sample`, has about 100 TimeCourse cases, picked by
  a script (S9) to cover every tag at least once, `comp` tags included (S11). The full suite (all 1790) follows once
  the sample's run time and the cluster's batch queue are known. FBA cases wait for a solver that does FBA in
  `solvers.yaml`.
- **S6. Failures go to known problems** ([plan-known-problems](plan-known-problems.md)), one per solver and case, with
  the case's tags as the category. Nothing is dropped from the suite because a solver can't do it.
- **S7. A tag view.** The suite run page groups rows by tag and shows each solver's pass rate per tag. This is the
  last step, and it uses the tags that S1's cache already holds.

## Decided in step 2 (Jim, 2026-11-05)

- **S12. A `comp` case that reports a submodel's element by its flattened id is a recorded failure** until SED-ML or
  process-bigraph-lang has a convention for addressing an element inside a submodel instance. These are the 79 cases
  of finding 10, for example 01126. The source fails with the reason (`… is not an element of the model as written
  (unflattened)`) on the suite row, and the case stays in the suite (S6), so it shows up once a convention lands. The
  model is still never flattened (S11). Testing these cases through a flattener belongs to the flattening service
  in "Later".

## Steps

1. **This plan.** Agree S1–S11 (S12 was added in step 2).
2. **The source.** `sbml-test-suite:` sources: fetch, hash check, cache, OMEX writer (S1, S2), and the reference with
   its origin (S3, S10), as `sedml/sbml_test_suite.py`. It also adds the `sbml_test_case` label. Tested on hand-written
   cases in the suite's layout: amounts and concentrations, a compartment sized by a rule, a flattened `comp` id, and
   an FBA case. Findings 9–11 come from running it over the real release.
3. **Tolerances per source** (S4), applied in the comparison and shown on the comparison page. A case's tolerances
   are `Tolerances(rel_tol=relative, abs_tol_min=absolute, abs_tol_scale=0)`. The platform's score puts the reference
   as `b`, so with no scaled term it is exactly the suite's criterion (a boundary test pins this). The suite run passes
   them to `service.submit` in place of the suite's, and the comparison's settings record `tolerances_from` (the
   source). The comparison page states `rtol` and `atol` in full, and where they came from. Only a source kind can set
   its own tolerances; a per-source override in `suite.yaml` waits until another suite needs one. Drift against a
   baseline already uses each comparison's own tolerances.
4. **The sample suite** (S5, S9), with the reference deciding (S3):
   - **The reference decides.** Today a suite row's verdict ("agree"/"differ", `suite_runs.py`) is whether the
     solvers agree with each other, and closeness to the reference is only shown, so three solvers that agree on a
     wrong answer read "agree". A suite setting makes the reference the arbiter: each solver on a row passes or fails
     against it, and the row's verdict and the suite's counts follow from those. Suites without the setting are
     unchanged (plan-sedml D7).
   - The picking script, then `examples/sbml-test-suite-sample/suite.yaml` on COPASI, Tellurium and VCell (S8), run
     on the cluster, baseline accepted, failures recorded as known problems (S6).

   **4a (built):** `suite.yaml` takes `judged_by: agreement | reference` (default `agreement`). Under `reference`
   each solver on a finished row passes when it completed and is close to the reference on every label the reference
   has (`suite_runs.passes`); a label it lacks fails it, which the comparison now records as an unscored
   `solver|origin` pair. The row passes when every solver does, the summary counts `passes_<solver>`, and a known
   problem excuses a row only when every solver without one passes. The suite page reads pass and fail, per solver.
   `scripts/sbml_sample_suite.py` writes the sample (finding 12): every tag and every pair of tags found together,
   chosen greedily, writable cases first, then the lowest number.
   **4b (done, 0.7.81):** run 1 (finding 13). Its baseline is not accepted: most of its failures are the platform's.
   **4c, the platform fixes, in this order** (Jim, 2026-11-05), each followed by a run:
   1. the archive carries a case's external models (compose-api);
   2. the solver steps report what SED-ML means: a species as an amount when it has only substance units, and every
      parameter and compartment that varies in time; `solvers.yaml` then says `provides: [species, parameter,
      compartment]` (pbsim_common, then a registry_env version);
   3. VCell's SBML import, cause by cause from finding 13, most cases per effort first, each with a failing case as
      its test (vcell-core, then libvcell, pyvcell, pbsim_common and a registry_env version);
   4. then the baseline, and known problems for what remains that S13–S16 do not explain.
5. **Features and incompatibilities** (S13–S16), after step 4c.
6. **The full suite.** All 1790 TimeCourse cases, after step 4 says it is affordable.
7. **The tag view** (S7), which becomes the feature × solver matrix of S16.

## Decided (Jim, 2026-11-05)

- **S8. Three solvers:** COPASI, Tellurium and VCell (`VCellUTCStep`, [plan-vcell-ode](plan-vcell-ode.md)). VCell's
  failures here are worth reporting upstream.
- **S9. A script picks the sample.** It reads the cached release and chooses a reproducible set of cases that covers
  every tag, preferring the fewest cases (step 4: every tag and every pair of tags found together; finding 12). It
  writes the suite's `sources` with each case's tags as a comment. Its output is committed, and re-running it at the
  same release gives the same list.
- **S10. Every case's expected results are the reference, however they were made.** A case with
  `generatedBy: Numeric` still uses the suite's `-results.csv`. Its source is annotated with that origin (on the
  reference and on the suite row), so a reader knows the answer came from a solver, not from an analytic solution.
- **S11. `comp` models go to the solver unflattened.** These cases test whether a solver reads `comp` correctly, so
  flattening first would test the flattener instead. A solver that can't read `comp` fails those cases, and that
  failure becomes a known problem (S6). This answers finding 1's 125 `comp` cases: they run as they are.
- **Deferred:** whether to offer the generated SED-ML to the SBML Team.

## Proposed after run 1 (Jim, 2026-11-05: "keep this order", after the platform fixes)

What a model needs and what a solver can do, said once and checked, so a solver that cannot do something fails with
a clear message rather than an import error, and the suite reads "unsupported" rather than "failed".

- **S13. The vocabulary is the SBML Test Suite's tags** (64 in 3.5.0, `comp:*` included). Its own Test Runner records
  a tool's unsupported tags the same way, so our results stay comparable with its results database.
- **S14. A model's features are detected, not only read.** A libsbml detector lists a model's tags from the model,
  so the same check applies to BioModels and biosimulations.org sources. The 1789 cases test it: its tags for each
  must match the case's declared ones.
- **S15. Incompatibilities are registry data.** Each is (solver, feature, status, reason, evidence), status
  `unsupported` (the solver refuses it) or `wrong` (it runs and gives wrong answers, the more dangerous kind), kept
  beside `solvers.yaml`, changed by pull request, and tied to environment versions, since a new libvcell can end one.
  A solver step that meets a feature it cannot handle raises one standard error naming the tag (for example
  `VCellUTCStep` mapping "Algebraic rules are not handled" to `AlgebraicRule`), recorded as an event.
- **S16. The suite reads them.** A solver whose model needs a declared `unsupported` feature is not run, and its row
  says why ("unsupported: AlgebraicRule"); no known problem is needed. A failure that names a tag no entry declares
  is a missing entry. Declared entries are checked as known problems are: one whose cases now pass is stale
  (resolved), and a failure on a feature a solver claims is a regression. Known problems stay for what no feature
  explains.

## Later (not in this plan)

- **A flattening service.** An endpoint that flattens a `comp` model into core SBML, for solvers that can't read
  `comp`. These 125 cases would test it: flatten, run on a solver that passes the core cases, and compare with the same
  expected results. That would be a suite of its own, separate from S11.
