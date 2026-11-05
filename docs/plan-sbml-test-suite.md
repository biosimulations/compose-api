# A suite from the SBML Test Suite: every ODE solver against the community's expected results

**Status (2026-11-05): draft, for discussion. Not yet the active plan** ([README](README.md): entry-updates is).
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

## Decisions (proposed)

- **S1. A new source kind, `sbml-test-suite:<case>`** (for example `sbml-test-suite:00001`), resolved against one
  pinned release: `sbml_test_suite: {release: 3.5.0, sha256: …}` in the suite's yaml. The archive is fetched once,
  checked against the hash, and cached like a BioModels archive (`sources._cache`).
- **S2. The source writes its own OMEX:**
  - the model at its highest level (`l3v2`, else the highest it has);
  - a SED-ML document with one uniform time course (`start`, `duration`, `steps`) and one report of the settings'
    `variables`, each an amount or a concentration as the settings say (finding 5).

  The writer is a pure function with tests per case shape. It lives in compose-api, not in process-bigraph-lang,
  since it is about this suite's files.
- **S3. The expected results are a reference that is an arbiter.** `-results.csv` becomes the reference
  `sbml-test-suite:3.5.0`. A solver passes a case when it is close to that reference within the case's own tolerances
  (finding 4). Agreement between solvers is still shown, but it doesn't decide.
- **S4. Tolerances per source.** A source can carry its own `Tolerances`, which win over the suite's. That is the
  smallest change that holds S3, and it may help other suites too.
- **S5. The suite starts small.** A first suite, `sbml-test-suite-core-sample`, has about 100 core TimeCourse cases
  chosen to cover every core tag at least once. The full suite (1790 TimeCourse cases, `comp` included) follows once
  the sample's run time and the cluster's batch queue are known. FBA cases wait for a solver that does FBA in
  `solvers.yaml`.
- **S6. Failures go to known problems** ([plan-known-problems](plan-known-problems.md)), one per solver and case, with
  the case's tags as the category. Nothing is dropped from the suite because a solver can't do it.
- **S7. A tag view.** The suite run page groups rows by tag and shows each solver's pass rate per tag. This is the
  last step, and it uses the tags that S1's cache already holds.

## Steps

1. **This plan.** Agree S1–S7 and the open questions.
2. **The source.** `sbml-test-suite:` sources: fetch, hash check, cache, OMEX writer (S1, S2), and the reference
   (S3). Tested on a handful of cases with known tricky settings (concentration output, `0D-Compartment`,
   `CSymbolDelay`).
3. **Tolerances per source** (S4), applied in the comparison and shown on the comparison page.
4. **The sample suite** (S5): `examples/sbml-test-suite-core-sample/suite.yaml`, run on the cluster, baseline
   accepted, failures recorded as known problems (S6).
5. **The full suite.** All 1790 TimeCourse cases, after step 4 says it is affordable.
6. **The tag view** (S7).

## Open questions

- Which solvers? COPASI and Tellurium as in the other suites, plus VCell (`VCellUTCStep`, plan-vcell-ode), whose
  failures here would be useful upstream.
- Should the sample be chosen by a script (tag coverage, reproducible) or by hand?
- Do we report the cases with `generatedBy: Numeric` differently? Their expected values are themselves from a
  solver.
- `comp` cases need flattening before most solvers read them. Does process-bigraph-lang or libsbml do it, and where?
- Should the generated SED-ML be offered upstream (the 3.4.0 variant suggests the SBML Team once wanted it)? Only with
  Jim's go, as with any outside contribution.
