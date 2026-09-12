# Testing plan: current state and candidate actions

**Status:** working document, opened 2026-09-11. Part 1 and Part 2 are findings, measured on that date and meant to
be checkable. Part 3 is a menu of candidate actions with sizes and costs. Most of it is still undecided; the
decisions get made by iterating on this file.

**What has been built (2026-09-11).** A4, F.a, F.b and F.c are no longer candidates: they are implemented and
merged into this branch. `pytest` now brings up a throwaway SLURM cluster whenever Docker is present and runs the
SSH and scheduler tests against it, with no key, no VPN and no opt-in. The eleven `skipif` decorators are gone,
replaced by `slurm` and `cluster_only` markers over a parameterized backend. The whole suite runs in about a minute.
Section F carries an **As built** note for each part. The exercise paid for itself immediately: the container
backend exposed a production bug, recorded as F13.

**Scope.** This repository (`compose-api`) and `pbest` are the subjects. The other repositories in the loop are
included as context and as sources of practice worth copying or avoiding: `platform`, `sms-api`, `biosim-client`,
`compose-server`, `process-bigraph`, `bigraph-schema`, `spatio-flux`, `pbg-vcell-fvsolver`, `vivarium-workbench`,
`viva-superpowers`.

`viva-superpowers` was surveyed on 2026-09-12 and added as §1.7. **It is `pbg-superpowers` renamed**, not a second
project: the GitHub API redirects the old name to the new one and it is the same repository, created 2026-05-09. A
local checkout under the old name is that repository. Inside it, `viva_superpowers/` is the package and
`pbg_superpowers/` is a back-compatibility import shim that warns on use.

`platform` was added on 2026-09-11 and is worth reading closely: it is the sibling service, it is the only repo here
with branch protection, and it fails on gating in exactly the opposite direction from this one. Figures are from
`main` at `75dc795` (2026-09-04); PR #107 adds practices `main` does not yet have, noted where relevant.

**A note on the vivarium-collective repositories.** They are read-only for this work. Any change there needs the
owner's agreement first, so actions below that would touch them are marked as such.

---

## Part 1. What exists

### 1.1 One inherited strategy

Every service repository in this loop was generated from the same project template, `fpgmaas/cookiecutter-uv` (or
its Poetry predecessor). The evidence is not circumstantial: `codecov.yaml` is **byte-identical across
`compose-api`, `pbest`, `sms-api`, and `biosim-client`** (md5 `16bd7611…`), and this repository's `mkdocs.yml`
still carries the template author's name in its copyright line.

The template supplies a coherent starting point: `make check` (pre-commit, mypy, deptry), `make test`
(pytest with coverage), a CI workflow with a Python matrix, and a codecov target of 90%. What follows is mostly the
story of how that starting point drifted in each repository without anyone re-deciding it.

### 1.2 The numbers

Measured 2026-09-11. "Run in CI" counts tests that actually execute, not tests that are collected and skipped.

| Repository | Test functions | Run in CI | What gates the rest | Coverage reported |
|---|---|---|---|---|
| **compose-api** | 25 collected | **9** | `SLURM_SUBMIT_KEY_PATH` is empty in CI | 45%, uploaded from one workflow |
| **pbest** | 23 | 21 | `hpc` marker, CI runs `-m "not hpc"` | measured, never uploaded |
| **platform** (backend) | 205 | ~188 | 17 `skipif` on a GCS credential or a SLURM key | **not measured at all** |
| **platform** (frontend) | 0 | 0 | there is no test runner | none |
| sms-api | ~1,392 | most | collection hook plus ~40 `skipif` | measured, never uploaded |
| biosim-client | 20 | 20 | nothing is gated | uploaded |
| compose-server | ~7, most bodies commented out | 0 | no workflow runs on push or PR | none |
| bigraph-schema | ~1,178 | all | nothing is gated | terminal only |
| process-bigraph | ~434 | most | `slow` marker, CI omits `--run-slow` | terminal only |
| vivarium-workbench | ~5,250 | most | 28-id quarantine file plus optional-dep skips | none |
| spatio-flux | 0 | 0 | there is no suite | none |
| pbg-vcell-fvsolver | 9 | 0 | there is no CI | none |

### 1.3 How this repository tests today

**Layout.** `tests/` mirrors the source tree: `api/`, `common/`, `simulation/`, `simulators/`. Fixtures live in
`tests/fixtures/` as a package and are re-exported by name from `tests/conftest.py`. Configuration is three lines in
`pyproject.toml`: `testpaths = ["tests"]` and an HTML coverage report.

**The fixture pattern is the strongest thing here.** Service singletons in `compose_api/dependencies.py` are saved,
replaced with a test instance, yielded, and restored on teardown. Seven services are swapped this way. It gives
isolation without a framework and it is used consistently. `sms-api` uses the same pattern, which suggests it
travelled deliberately.

**Real dependencies, not mocks.** Postgres, NATS, and MongoDB come up as testcontainers, so Docker is required for
most of the suite. The API is exercised in-process through an ASGI transport rather than over a socket. The only
hand-written doubles are a data service and a background-task collector in `tests/fixtures/mocks.py`.

**The gate.** Eighteen `skipif` decorators share one condition: an empty `slurm_submit_key_path` in settings. No
workflow supplies that key, and the only secrets any workflow holds are a GitHub token and a codecov token. So the
gate is closed in CI, always.

**One file is excluded by naming.** `tests/simulation/dont_test_sedml.py` holds three tests that pytest never
collects.

### 1.4 How pbest tests today

**23 tests across 9 files**, mirroring the source layout. Two are marked `hpc` and CI deselects them. Two more are
gated on a live Docker daemon, which CI's runner has, so those do run.

**There are no test doubles at all.** No mocks, no monkeypatching, no containers. Tests drive real COPASI and
tellurium in-process, run real `docker buildx build` and `docker run`, and compare CSV output numerically to a
tolerance of 5e-8. For a library whose job is to build containers and submit jobs, this is a defensible choice: the
things worth testing are the real integrations.

**Twelve test functions are commented out**, including the entire whitelist-rejection matrix in
`tests/containerization/test_whitelist.py` and the arm64 image build.

### 1.5 How platform tests today

The sibling service, and the most useful comparison in this document because it is the same kind of system solving
the same problem with different choices.

**Backend: 205 tests across 29 files**, `backend/tests/` mirroring the package. The DI pattern is the same as ours
and slightly better executed: seven paired `set_`/`get_` accessors in `dependencies.py`, every fixture saving,
swapping, yielding and restoring. The database fixtures go further and pair the restore with explicit data cleanup,
with a comment naming the exact bug it prevents, since a session-scoped Mongo container would otherwise hand a later
test a stale success record.

**Real infrastructure, not mocks, for the hard parts.** Two testcontainers, Mongo and Keycloak, plus a real Temporal
dev server via `start_local`. Nothing guards Docker availability, so on a machine without it a bare `pytest` errors
rather than skips.

**Frontend: zero tests.** No runner, no spec files, and the required `frontend-ci` check is lint and typecheck only.

**Coverage: none at all.** No `pytest-cov` in the lockfile, no config, no upload, and no `codecov.yaml`. Two
documents advertise `uv run pytest --cov=biosim_server`, which cannot run.

**Gating is documented but not enforced.** Two markers are declared, `integration` and `integration_local`, and the
prose in four files says to run `-m "not integration"`. Nothing implements it: `lefthook.yml` runs ruff, eslint,
mypy and typecheck but **no tests at all**, so the first execution of the suite for any change is in CI.

### 1.6 What PR #107 adds that `main` does not have

Worth recording separately, because these are the practices this repo should be copying and they are arriving now
rather than already present:

- **A failure matrix over a mocked transport.** `tests/pages/test_run_page.py::test_failure_policy` parametrizes
  four resources against six failure modes, 24 cases per route, asserting both the resulting status and that no
  upstream body leaked into the response.
- **Assertions that no upstream request happened** (`seen == []`) on every rejection path, so the guarantee is that
  the transport was never entered rather than merely that the status was right.
- **Leak assertions** (`assert "secret" not in response.text`) on every failure case.
- **OpenAPI contract tests in pytest**, rather than only the shell `curl | jq` in the smoke job.
- **`httpx.MockTransport`**, which `main` does not use anywhere — and its absence is precisely why the live calls
  described in F10 get through.

### 1.7 How viva-superpowers tests today

Surveyed 2026-09-12. It is a Claude Code plugin of seventeen skills plus a Python helper package for building
process-bigraph models, depending on `bigraph-schema` and `process-bigraph` directly. It is a sibling of `pbest`,
not a consumer: there is no `pbest` dependency.

**By far the largest suite in this survey, and the fastest.** 121 test files, roughly 1,390 test functions expanding
to about 1,560 collected items, last green run 34 seconds. Counts are from a repository scan, not from a run here.
No Docker, no testcontainers, network calls mocked at `urllib.request.urlopen`. The whole suite runs offline.

**Layout is flat and tiered by filename** rather than by directory: `test_e2e_happy_path.py`,
`test_integration_observable_pipeline.py`, `test_cross_harness.py`. `conftest.py` is seventeen lines and three path
fixtures. Roughly twenty-eight files assert on *authored artifacts* rather than code: skill manifests, naming
conventions, a discovery contract, report linting.

**Twenty-six tests skip at runtime**, gated on an absent upstream template checkout, an uninstalled optional
dependency, and — the one that matters — **private workspace data that CI will never have.** The golden scientific
studies are the highest-value assertions in the suite and they are green-by-absence forever, because `pytest.skip()`
on missing data is indistinguishable from passing. This is the same shape as F1 here, arrived at by a different route.

**It is clean on config shadowing.** No `pytest.ini`, `tox.ini` or `setup.cfg` anywhere; the `pyproject.toml` block
is the sole live config. It is the counter-example to F11.

**It repeats three of our own mistakes**, which is the most useful thing the survey found:

- **CI does not gate merges.** Branch protection on `main` requires one review and enforces admins, but carries **no
  required status checks at all**, so a red build does not block a merge. Verified against the API on 2026-09-12.
  This is F3 in a repository that *has* branch protection, which is worse than not having it: the protection implies
  a gate that is not there.
- **It runs its CI twice**, `on: [push, pull_request]` with no branch filter. F4, second instance.
- **Its matrix does not test Python versions.** The matrix varies operating system only and both legs hardcode
  3.11, while `requires-python` declares `>=3.11`. So 3.12 through 3.14 are advertised and never exercised, and one
  module already skips itself in CI for requiring 3.12. F5, second instance, by a different mechanism than ours.

Also: `pytest-cov` is a declared dev dependency and is never invoked, there is no type checker, and ruff is narrowed
to two rules over one directory with `tests/` unlinted entirely.

**A note on scope.** `viva-superpowers` is a `vivarium-collective` repository. Nothing in this document is to be
changed there without the owner's agreement, including opening an issue. The single highest-value fix is one line,
adding required status checks to `main`, and it is not ours to make.

---

## Part 2. Findings

Ranked by how much they cost. Each is stated so it can be disproved.

### F1. The tests that would prove the system works never run in CI

In this repository, 16 of 25 tests are gated on an HPC credential that no workflow provides. What executes are
import checks, database round-trips, and one serialization test. What does not execute is the entire reason the
service exists: submit a simulation to SLURM, monitor it, fetch the results.

`pbest` has the same shape with different mechanics: its two `hpc` tests cover batch submission and the remote path,
and CI deselects both by flag.

This is not an accident of neglect. It is a deliberate design that was never finished. The gate exists so that a
developer without a cluster can still run the suite, which is right. What is missing is any second tier where the
gated tests do run, on a schedule or against a stand-in.

The consequence is concrete. Several changes merged in this session touched the HPC path, and no automated check
could have caught a regression in it.

### F2. Coverage is measured, targeted, and enforced nowhere

All four service repositories declare `target: 90%` in an identical `codecov.yaml`. The template's upload step is
conditioned on `matrix.python-version == '3.11'`, and every repository changed its matrix without revisiting that
condition:

| Repository | Matrix | Upload condition | Fires? |
|---|---|---|---|
| compose-api `main.yml` | 3.9–3.13 | `== '3.11'` | yes |
| compose-api `ci-test.yml` | 3.12, 3.13 | `== '3.11'` | **no** |
| pbest | 3.12 | there is no upload step | **no** |
| sms-api | 3.13 | `== '3.11'` | **no** |
| biosim-client | 3.8–3.12 | `== '3.11'` | yes |

`platform` is the other end of the same failure: it never adopted the template's `codecov.yaml` at all, has no
`pytest-cov` in its lockfile, and measures nothing — while two of its documents advertise a `--cov` command that
cannot run. Four repos carry an unenforced 90% target; the fifth carries no target and no measurement. Neither end
produces a number anyone acts on.

Actual coverage here is **45%** against a stated target of 90%, and no pull request carries a codecov status check.
The worst-covered modules are the ones the HPC gate hides: `slurm_service` at 18%, `job_monitor` at 20%,
`ssh_service` at 23%, `handlers` at 19%.

### F3. Neither repository has branch protection

`gh api repos/biosimulations/compose-api/branches/main/protection` returns "Branch not protected", and so does
pbest's. Every check on every pull request in both repositories is advisory. A red pull request can be merged, and
a direct push to `main` is possible.

`pbest/CLAUDE.md` states that `main` "is protected: no direct pushes, changes land through a PR". That is not true
today, and a stale instruction is worse than none because it stops people checking.

**`platform` shows this is achievable in the same organisation, and what it costs.** Its `main` requires two
contexts, `build` and `build (ubuntu-latest, 24)`, with `strict: true` so a branch must be current before merging.
It requires **zero** approving reviews, which is a deliberate trade: the machine gates, humans are not forced to.
Notably `smoke`, its only cross-service test, is **not** required, so the check that would catch a broken
integration is the one that cannot block.

### F4. This repository runs its CI twice

`.github/workflows/main.yml` and `.github/workflows/ci-test.yml` are both named "Main" and both define `quality`,
`tests-and-type-check`, and coverage steps. One triggers on pull requests and pushes to `main`; the other on every
push to any branch. On a pull request branch both fire.

That is why every pull request shows two `quality` jobs and seven `tests-and-type-check` jobs. Roughly half the CI
minutes spent on this repository are duplicate work, and the duplication also explains why the codecov condition
appears twice with different matrices.

**Second instance, 2026-09-12.** `viva-superpowers` does the same thing with a single workflow triggered
`on: [push, pull_request]` and no branch filter (§1.7). The fix in both cases is to filter the push trigger to
`main`. Here the duplication is no longer only a cost: it doubles the SLURM clusters and image pulls a single push
starts, which is what made the worker startup race in group F fire intermittently on busy runners.

### F5. The Python matrix does not test Python versions

The composite action installs an interpreter with `setup-python`, then runs `uv sync`, which ignores it and uses
`.python-version` instead. A CI log from this week shows both lines:

```
Successfully set up CPython (3.12.14)
Using CPython 3.14.7
```

All seven matrix legs execute the same interpreter. The matrix costs seven times the minutes and proves nothing
about version compatibility. The same is true in every repository here that has a matrix.

**Fixed here on 2026-09-11.** The composite action now exports `UV_PYTHON` from the matrix value, which pins every
later `uv sync` and `uv run` in the job, and prints the interpreter it ended up with. The matrix itself was cut from
seven legs to `3.13` and `3.14`: `requires-python` is `>=3.13.2`, so the older legs were claiming to test versions
the project does not support. The suite was run against a real 3.13 before the change landed. The remaining
repositories with a matrix are untouched and still have this problem.

**Second instance, 2026-09-12.** `viva-superpowers` reaches the same outcome by a different mechanism: its matrix
varies operating system only and both legs hardcode 3.11, while `requires-python` declares `>=3.11` (§1.7). So the
check worth running on any repository here is not "is there a matrix" but "does a matrix leg actually change the
interpreter".

### F6. The risk profile is inverted

The pure library with no I/O is exhaustively tested: `bigraph-schema` has about 1,178 tests, no gating, and a
systematic type-by-method matrix where each schema type gets a class and each method a cell. Everything runs in CI.

The distributed system with SSH, SLURM, Postgres, NATS, and container builds runs nine tests.

Two repositories in the composition path have effectively nothing. `spatio-flux`, the demo library named in the
paper, has no suite at all; its `tests.py` is a demo script with no assertions and four of seven demos commented
out of its own entry point. `pbg-vcell-fvsolver` has nine genuinely good numerical tests, including mass
conservation to 2%, and no CI to run them.

### F7. Two of the nine tests that run in CI are unreliable, for different reasons

Both were observed on **docs-only** pull requests during a single afternoon, which is the point: neither could
possibly have been caused by the change under review.

**A race, in `tests/common/test_nats.py::test_sync_producer_with_async_subscriber`** (PR #161):

```
AssertionError: assert b'hello world 5' == b'hello world 9'
```

A race between the synchronous producer and the asynchronous subscriber. The proof that it is not a regression is
that the duplicated CI (F4) ran the same commit twice on the same Python and one leg passed while the other failed.
It also passes locally three times out of three.

**An external dependency, in `tests/api/test_hpc_run_serialization.py`** (PR #164):

```
docker.errors.APIError: 500 Server Error ... fromImage=postgres
  Head "https://registry-1.docker.io/v2/library/postgres/manifests/15": ...
  read: connection reset by peer
```

Docker Hub reset the connection while the Postgres testcontainer was being pulled. A rerun passed. Nothing in the
repository is at fault, and nothing in the repository defends against it either: there is no retry, no registry
mirror, and no pre-pull step.

**Why this matters more than the raw count suggests.** Only nine tests execute in CI (F1), so two unreliable ones
are roughly a **22% false-failure rate on the entire signal**. Combined with the absence of branch protection (F3),
the practical effect is to train people to merge past red checks — precisely the habit that makes a suite
worthless, and the habit that then hides a real failure when one arrives.

**The second one connects to F10.** `platform`'s CI is coupled to third-party uptime through live API calls; ours
is coupled to it through container image pulls. Same exposure, different door, and neither repo defends against it.
Any fix for F1 that adds more containers — the SLURM cluster in A4 pulls about 2.8 GB — widens this surface rather
than narrowing it, so a registry mirror or a pull-retry belongs in that work rather than after it.

### F8. The SSH dependency is located, not injected

**First, what is not wrong.** `get_ssh_service()` (`compose_api/common/ssh/ssh_service.py:111`) returns a fresh
`SSHService` on every call, and that is deliberate and correct. `SSHService` is a **stateless value object**: it
holds four connection parameters and no connection. Each of its methods opens its own connection and closes it, and
`close()` is a documented no-op — *"nothing to do here because we don't yet keep the connection around."*

So there is no session lifecycle to own, construction is free, and a singleton would buy nothing. Per-call
construction is also safer than a captured instance, because it picks up configuration changes rather than pinning
them. There is a further reason: a long-lived SSH connection to an HPC login node is dropped by idle timeouts, so a
persistent session would need liveness checks, reconnect, and retry. Constructing per operation sidesteps all of
that. The word "yet" in that comment shows pooling is the anticipated future, and the factory shape is exactly what
lets it be added later behind the same interface.

Contrast the five services that *are* injected in `dependencies.py`: a database engine with a connection pool, a job
monitor with a background polling task, a database service with sessions. All stateful, all needing singleton
lifecycle. SSH is not like them, and treating it the same would be the mistake.

**What is wrong is narrower: the dependency is located rather than declared.** `SimulationServiceHpc` has no
`__init__` at all. A static method reaches into the global factory at the point of use:

```python
@staticmethod
def _get_services() -> tuple[SlurmService, SSHService, Settings]:
    settings = get_settings()
    ssh_service = get_ssh_service()
    return SlurmService(ssh_service=ssh_service), ssh_service, settings
```

That is the service-locator pattern: the dependency is buried in the implementation instead of appearing at the
boundary, so a test can only redirect it by mutating a global. `simulation_service.py:216` calls the global factory
a second time directly, and `data_service.py:28` exposes it as a property.

**It is also the outlier.** `SlurmService.__init__(ssh_service=...)` already takes its dependency as a constructor
parameter, and `DataService.__init__(settings: Settings | None = None)` already uses the inject-or-fall-back idiom
for settings. `SimulationServiceHpc` is the one class that does neither.

There is also plain duplication: `dependencies.py:175` constructs an `SSHService` inline from the same four
settings fields instead of calling the factory, so the construction logic lives in two places.

Evidence someone hit this: `tests/fixtures/slurm_fixtures.py:37` contains a commented-out
`set_ssh_service(saved_ssh_service)` calling a function that does not exist.

The fix is F.b below, and it is small.

### F9. Settings have no override seam, and the obvious one does not compose

Services sit behind a mutable module-level singleton with a setter. Settings sit behind `@lru_cache`
(`compose_api/config.py:90`), which has a getter and no setter. Same intent, only one has a seam.

The obvious fix — save the whole `Settings`, `model_copy` it with overrides, restore on teardown — is wrong in a
way worth writing down, because it *appears* to work. Under pytest's LIFO teardown, two fixtures overriding
disjoint fields do compose. But they compose **by accident of ordering, not because the fields are disjoint**, and
the same mechanism fails three ways:

1. Two fixtures overriding the *same* field resolve silently to whichever ran second. No conflict is reported.
2. Any object constructed during the first fixture's lifetime holds that snapshot, so a later override never
   reaches it.
3. A fixture cannot be read locally: its correctness depends on what else is active and in what order.

All three have one cause: **the unit of override is the whole object, so the system cannot tell disjoint overrides
from conflicting ones.** The five service singletons do not have this problem because each concern owns its own
slot; disjointness is structural. Settings is the one place that property was lost.

**What is not a problem.** Only two settings reads in production code happen at module scope, and both are
`assets_dir` (`data_service.py:17`, `api/main.py:50`). Every read on the SLURM path is inside a function —
`hpc_utils._namespace_path()`, `get_internal_experiment_dir()`, `get_ssh_service()`,
`SimulationServiceHpc._get_services()`, `job_monitor.py:39` — so an override genuinely reaches the code under
test. `CLAUDE.md`'s warning that settings changes require a process restart is true only of those two constants and
is overly broad as written.

### F10. Two repos fail at gating in opposite directions, and both are wrong

This one only becomes visible by comparing, which is why `platform` earns its place in this document.

**Here, everything real is skipped.** 16 of 25 tests are gated on a credential CI never has (F1), so CI proves
imports and database round-trips and nothing about the system's purpose.

**In `platform`, the live tests run in the required check.** Its CI invocation is bare:

```yaml
- name: Run tests
  run: uv run python -m pytest
```

No marker selection. So three tests hit third-party services on every pull request:
`test_get_simulator_spec_real_api` and `test_find_compatible_simulators_real_api` reach `api.biosimulators.org`,
and `test_get_simulation_versions_rest` does too — that third one carries **no marker and no skipif**, so it
survives even the documented `-m "not integration"` escape hatch. A `vcell` delisting or an upstream outage reds a
required check on unrelated work. `WorkflowEnvironment.start_local` also downloads the Temporal binary from the
network on first use, a second uncontrolled dependency.

The two failures share a cause: **in neither repo does the marker decide where the test runs.** Here the gate is a
credential that happens to be absent; there the intent lives in prose that nothing enforces, in four documents and a
file banner, while `lefthook.yml` runs no tests at all so nobody discovers the drift locally.

That is the argument for F.c's rule — mark by what a test *needs*, then let the runner decide what to supply — and
it is worth noting that `platform`'s `smoke.yaml` already gets this right in its own header, stating it deliberately
avoids a real submission because of "minutes and flaky external state". Its backend suite does not follow its own
smoke job's policy.

### F11. Config shadowing silently disables settings in three repos

`pytest` takes the first `pytest.ini` it finds and never merges `[tool.pytest.ini_options]` from `pyproject.toml`.
Three repos here have both, so one block is dead in each: `platform`, `sms-api`, and `biosim-client`.

In `platform` the dead block is doing real damage in waiting. It contains:

```toml
python_files = "main.py"
```

which, if the `pytest.ini` were ever removed as redundant, would treat only `main.py` as a test module and collect
**zero** tests — a green suite that runs nothing. The shadowing is currently the only thing preventing that.

In `biosim-client` the shadowing works the other way: with `testpaths` dead, a bare `pytest` also collects 35
generated OpenAPI stub files that CI's `pytest tests` does not.

~~This repo has only the `pyproject.toml` block and is unaffected~~ — **wrong, corrected 2026-09-11.** This repo had
both. A two-line root `pytest.ini` holding only `log_cli` settings was silently disabling the entire
`[tool.pytest.ini_options]` block in `pyproject.toml`: `testpaths`, `addopts`, and, as of this branch, the `slurm`
and `cluster_only` marker registrations. The symptom was `PytestUnknownMarkWarning` for markers that were plainly
declared, which is what led back to the cause. The `pytest.ini` is deleted and its two settings folded into
`pyproject.toml`, so there is now one file.

The general check stands, and this repo is the argument for it: if both exist, say out loud which one is live.
`tox.ini` was stale in the same way, still declaring `py39` through `py312` envs that `requires-python` forbids; it
now lists `py313` and `py314`. Nothing invokes tox, which is why nobody noticed.

**A clean counter-example, 2026-09-12.** `viva-superpowers` has no `pytest.ini`, `tox.ini` or `setup.cfg` at all,
so its `pyproject.toml` block is unambiguously live (§1.7). Having one config file is the whole fix.

### F12. Smaller things worth fixing while nearby

- `tests/simulation/dont_test_sedml.py` (3 tests) and 12 commented-out tests in pbest are dead weight. Either
  restore them or delete them, but leaving them as text misleads.
- `pbest`'s CI has no `pull_request` trigger, so its checks never appear on a pull request.
- `pbest` measures coverage and discards it.
- `process-bigraph`'s REST and Ray transports are covered only by `slow` tests that CI never enables, so those
  transports are untested in every realistic environment. Relevant to us because the composition protocol's remote
  story rests on them.
- ~~Coverage is uploaded to Codecov on the Python 3.11 leg~~ — **fixed 2026-09-11.** There was no 3.11 leg, so the
  condition was never true and coverage had stopped reaching Codecov entirely. It now runs on the 3.13 leg.
- ~~`tests/simulators/test_readdy.py` writes its results to a fixed path~~ — **fixed 2026-09-11.** It wrote to a
  named developer's Desktop, so the test could not pass for anyone else. It uses a temporary directory now.

---

### F13. A job seen as PENDING was abandoned by the monitor

Found on 2026-09-11 by running the existing scheduler test against the container, where the poll interval is short
enough to catch a job before it starts. `JobMonitor` re-reads its work list every tick from a query that selected
**only** rows whose status was exactly `RUNNING`. Runs are inserted as `RUNNING`, so the first poll that saw the
job still queued wrote `PENDING` and thereby removed the row from every later poll. The run then stayed `PENDING`
forever: it never reached `COMPLETED`, the results were never fetched, and the API reported it as queued
indefinitely.

Nothing caught this because the only tests that exercise the monitor were the ones gated behind a real cluster, and
on a cluster the behaviour is intermittent rather than deterministic: it happens exactly when a job is still queued
at the first poll, which is the common case on a busy queue and the rare case on an idle one.

The query now selects everything that has not reached a terminal status, with the terminal set named explicitly so
a status added later keeps being polled instead of being silently dropped. `list_running_hpcruns` is renamed
`list_unfinished_hpcruns`, because the old name described the bug. Covered by `tests/simulation/test_job_polling.py`,
which needs only Postgres and so runs everywhere, on every status in the enum.

**This is the argument for A4 in one finding.** The bug was reachable only by running the monitor against a real
scheduler. It had been latent for as long as those tests have been skipped.

### F14. A published wheel can declare a dependency that does not exist, and nothing here would catch it

Learned from `viva-superpowers` on 2026-09-12 rather than from our own breakage, which is the point of surveying
siblings.

**The failure class.** A `[tool.uv.sources]` entry redirecting a dependency to a git URL is *workspace-local*. It is
not written into a built wheel. The wheel declares a bare `Requires-Dist` that a downstream consumer must resolve
from PyPI, and if the package is not there, the install fails for them and never for us. `viva-superpowers` shipped
a broken 0.14.0 exactly this way, and its `pypi-installable` workflow header records the incident.

**Our exposure is the client, not the service.** This repository is never installed as a wheel: it ships as a
container built with `uv sync --frozen` (`Dockerfile-api:30,36`), which honours `uv.sources`, and there is no
publish workflow here. The published artifact is `compose-api-client`, generated into a separate repository that is
not in this workspace and that I have not inspected. `pbest` installs it from PyPI. That is where the check belongs.

**The trap is already set here, though it has not sprung.** `pyproject.toml:75-76` carries

```toml
[tool.uv.sources]
bsander = { git = "https://github.com/biosimulators/bsander.git" }
```

`bsander` appears in no dependency list and in no lock entry, and `pypi.org/pypi/bsander/json` returns 404. The
override is therefore inert: `uv.sources` only redirects something actually depended upon. It costs nothing to
delete, and deleting it removes a line that would silently become load-bearing the moment someone adds `bsander` to
`dependencies`.

Size S. The action is two things: drop the dead override here, and add a wheel-installability preflight to the
client repository, not to this one.

## Part 3. Candidate actions

Sized as S (under a day), M (a few days), L (a week or more). Nothing here is chosen.

### A. Close the CI gap on the HPC path (addresses F1)

1. **A fake SLURM.** Implement the `SlurmService` interface against a local process table so submission, polling,
   and completion can be exercised without a cluster. Ungates the scheduler and monitor tests. Size M. Cost: a
   second implementation to keep honest; a fake that drifts is worse than no test.
2. **A scheduled real run.** Keep the tests as they are and run them nightly against the real cluster from a
   workflow holding the key as a secret. Size S. Cost: a secret in CI, a flaky-on-VPN job, and failures arrive the
   next morning rather than on the pull request.
3. **Record and replay.** Capture real `squeue`/`sacct` output and SSH transcripts once, replay them in CI. Size M.
   Cost: recordings rot silently when the cluster's output format changes.
4. **Containerized SLURM in a testcontainer.** **Chosen and implemented on 2026-09-11.** See A4 below for the
   measurement that decided it, and the As built note at the end of that section for what shipped.
5. **Do nothing, but say so.** Document that the HPC path is covered by manual testing only, and stop implying
   otherwise with a 90% coverage target. Size S.

#### A4 in detail: measured, not estimated

Two candidate images were run on 2026-09-11 and each driven through **this repository's real `SSHService` code
path and `SlurmJob` parsers** — not through a separate SSH client written for the test. Both work. The second is
clearly better.

##### The comparison

| | `xenonmiddleware/slurm:latest` | `giovtorres/slurm-docker-cluster` |
|---|---|---|
| SLURM version | 17.02.6 (March 2020) | **26.05.2** (August 2026) |
| Architectures | amd64 only | **amd64 and arm64** (native on an Apple-silicon laptop) |
| Shape | one container | compose cluster: mysql, slurmdbd, slurmctld, slurmrestd, 2 workers |
| SSH | must be added by hand | **built in, key-only** |
| `sacct` (needs slurmdbd) | works | works |
| Singularity / Apptainer | absent | **both present** at `/usr/bin/` |
| Startup | ~1s | ~19s, including healthchecks |
| Teardown | instant | ~1s |
| Disk | 648 MB | 2.33 GB + 485 MB MariaDB |
| Maintained | last pushed 2020 | last pushed 2026-08-09 |

**Recommendation of record: `giovtorres/slurm-docker-cluster`.** The nine-year version gap is the deciding factor:
pinning our parsers against SLURM 17 output would encode a format the real cluster no longer produces.

##### What was proved, on the modern cluster

```
compose up + healthchecks: OK  (wait=True, no sleep)
exec_in_container -> exit=0  stdout='cpu* up 2 idle\ngpu up 0 n/a'  (types: str)
get_service_port('slurmctld', 22) -> 56812
asyncssh key auth (root@slurmctld): OK
sbatch --parsable -> '1'  (int-parseable: True)
squeue raw: '1|wrap|root|root|PENDING'
  parsed squeue -> job_id=1 name='wrap' account='root' state='PENDING'
sacct raw:  '1|wrap|root|root|COMPLETED|2026-09-11T18:24:35|2026-09-11T18:24:37|00:00:02|0:0|'
  parsed sacct  -> job_id=1 state='COMPLETED' elapsed='00:00:02' exit='0:0'
scp_upload: OK
sbatch of uploaded file -> 2
```

Those are the exact commands `SlurmService` issues, parsed by `SlurmJob.from_squeue_formatted_output` and
`from_sacct_formatted_output`. Note `account='root'` rather than the ancient image's `(null)` — closer to real
cluster output.

##### SSH is built in, and is the right shape

This is the single most important correction to the obvious assumption (and to at least one AI-generated
walkthrough of this image, which claims the opposite and proposes installing `openssh-server` at container start).
The Dockerfile installs `openssh-server` and configures it **key-only** (`PasswordAuthentication no`,
`PermitRootLogin prohibit-password`); `docker-entrypoint.sh` copies a host-mounted `authorized_keys` into
`/root/.ssh/` and starts `sshd`; the compose file already publishes container port 22. Three environment variables
turn it on:

```
SSH_ENABLE=true
SSH_AUTHORIZED_KEYS=/host/path/to/authorized_keys   # bind-mounted read-only
SSH_PORT=0                                           # 0 = random host port; default 3022
```

Key-only root login to a head node is exactly our production shape, so the fixture exercises the real
authentication path rather than a password shortcut.

##### Using it from testcontainers

`testcontainers.compose.DockerCompose` drives it. The signatures in the installed version (4.x) are worth writing
down, because they differ from what is commonly assumed:

```python
DockerCompose(context, compose_file_name=None, pull=False, build=False, wait=True, ...)
exec_in_container(command, service_name=None) -> tuple[str, str, int]   # (stdout, stderr, exit_code), all str
get_service_port(service_name=None, port=None) -> int | None
```

The first argument is `context`, positional. `exec_in_container` returns the exit code **last**, and returns `str`
rather than `bytes`, so decoding is unnecessary. `wait=True` is already the default and every service in the
compose file has a healthcheck, so a fixed sleep is both unnecessary and less reliable.

##### Covers and does not cover

**Covers.** `sbatch --parsable`, both status-parsing paths, `scp_upload`, real state transitions, and the sbatch
heredocs in `simulation_service.py` actually executing. That is precisely the code the HPC gate hides today:
`slurm_service` 18%, `handlers` 19%, `job_monitor` 20%, `ssh_service` 23%.

**Possibly also covers the container-build path.** Unlike the older image, Singularity and Apptainer are both
installed, so the `BUILD_CONTAINER` job type may be exercisable too. Not yet proved: `singularity build
--fakeroot` typically wants privileges a default container does not have. Worth one experiment before counting on
it.

**Does not cover.** The cluster's real partition and QoS names (`cpu`/`gpu` here versus the production names), the
real filesystem layout, and anything about the production scheduler's configuration.

##### One prerequisite code change

`SSHService.__init__` accepts hostname, username, key path, and known hosts — **there is no port parameter**, and
none of its three `asyncssh.connect` call sites passes one, so it can only reach port 22. A container publishes a
random high port. Adding `port: int = 22` and threading it through those three calls is the whole change, and it
is defensible on its own merits.

##### Two practical cautions

**Pull the prebuilt image and retag it.** The compose file references the local tag
`slurm-docker-cluster:${SLURM_VERSION}` behind a `build:` block that compiles SLURM from source with `rpmbuild`.
Left alone the first run is a long build. `docker pull giovtorres/slurm-docker-cluster:26.05.2` followed by
`docker tag giovtorres/slurm-docker-cluster:26.05.2 slurm-docker-cluster:26.05.2` skips it.

**Seven services declare a fixed `container_name`.** Two runs on one host collide. One job per CI runner is fine;
local parallel runs need care, or an override removing the fixed names.

##### Suggested shape if this is chosen

A session-scoped fixture that brings the cluster up with `DockerCompose(..., wait=True)`, writes a generated public
key to the `authorized_keys` path the entrypoint expects, reads the mapped port with `get_service_port`, and yields
a real `SSHService` pointed at it. The existing `skipif` gate then changes meaning: instead of "skip unless a
cluster credential exists", it becomes "use the real cluster when a credential exists, otherwise use the
container". Same tests, two backends.

Size **S–M**: the fixture and the `port` parameter are small; the judgement call is whether a ~2.8 GB pull and a
20-second startup belong in the per-pull-request job or in a separate one.

**As built (2026-09-11).** `tests/fixtures/slurm_cluster/docker-compose.yml` vendors the upstream stack with four
deliberate changes: the published multi-arch image is used directly so nothing compiles on first run; no
`container_name:` anywhere, so two runs on one host do not collide; port 22 is published on host port `0` and read
back with `docker compose port`, so concurrent runs and CI pick free ports; and slurmrestd, the GPU worker and the
portal are dropped. `COMPOSE_PROJECT_NAME` is set per session to a random value and must be threaded to the worker,
whose entrypoint resolves its own replica index over DNS and will not start without it.

The cluster comes up in about twenty seconds and the container-backed tests finish in under a minute. Two
adjustments were needed beyond the plan: the production code creates a per-experiment directory but never its
parents, so the fixture provisions the same tree an administrator made once on the real cluster; and the scheduler
test asserted status after a fixed sleep, which is a race on any backend and was replaced with polling.

**Extended 2026-09-11.** The backend was initially declared unable to build container images. That was wrong,
and only a configuration gap: with a subordinate id range mounted over `/etc/subuid`, the container pulls from a
registry, builds a definition file with `singularity build --fakeroot`, and runs the result from inside a SLURM job
on a worker node. `tests/simulation/test_container_lifecycle.py` now drives the production `download_container` and
`build_container` against a busybox definition, in seconds. The nine `cluster_only` tests stay where they are: what
the container lacks is the real simulator images and the minutes it takes to build them, not the machinery.

The wider question this raises -- whether to keep a second image format at all -- is
[plan-container-runtimes.md](plan-container-runtimes.md).

### B. Make coverage mean something (addresses F2)

1. Fix the upload condition to match the matrix, or drop the condition, so coverage is reported from one place.
   Size S.
2. Set the target to the truth (about 45%) and ratchet it upward, rather than leaving an aspirational 90% that
   nothing enforces. Size S.
3. Add the codecov status as a required check, which depends on A and C. Size S once the others land.

### C. Fix the CI structure (addresses F3, F4, F5)

1. Delete one of the two duplicate workflows. Size S. Halves CI minutes immediately.
2. Collapse the matrix to the one interpreter actually used, or pass `--python` through to `uv sync` so the matrix
   does what it claims. These are opposite choices and the decision is whether multi-version support is a real goal.
   Size S either way.
3. Turn on branch protection with the checks that matter, and correct the claim in `pbest/CLAUDE.md`. Size S.
   Cost: solo pushes to `main` stop working, which is the point.

### D. Raise the floor in the composition path (addresses F6)

1. A smoke test for `spatio-flux`: build one composite, run a few steps, assert the fields changed. Size S, but it
   is a `vivarium-collective` repository, so it needs the owner's agreement.
2. CI for `pbg-vcell-fvsolver`, which already has good tests and no runner. Size S, same ownership caveat.
3. Adopt the golden-vector practice more widely. The artifact-address vectors are pinned identically in
   `process-bigraph` and `vivarium-workbench`, with an object-identity assertion preventing a hand-ported copy.
   That is the right shape for any wire format we settle on in the protocol work, including the OpenAPI contract
   this repository publishes to pbest. Size M.

### E. Tidy (addresses F7, F11, F12)

State in each repo's `pyproject.toml` which pytest config is live where both exist (F11) — a one-line comment,
since the shadowing is invisible and one of the dead blocks would collect zero tests if the file shadowing it were
ever removed as redundant. Then: fix the `test_sync_producer_with_async_subscriber` race (wait on the subscriber rather than assuming
ordering); decide how image pulls are defended, whether by a retry, a registry mirror, or an explicitly accepted
risk; restore or delete the dead tests; add a `pull_request` trigger to pbest; upload or stop measuring pbest's
coverage. Size S in total. The two unreliable tests are worth doing first and on their own: while only nine tests
run in CI, two of them flaking is roughly a 22% false-failure rate on the whole signal.

---

### F. One test body, two backends (addresses F1, F8, F9, F10)

The companion to A4. A4 answers "can we run SLURM in CI"; this answers "how do the same tests run against both the
container and the real cluster without the two drifting apart". It has three parts, and the first two are
prerequisites rather than choices.

#### F.a Give settings a composable override seam (addresses F9)

Replace whole-object replacement with a stack of **partial layers removed by identity**, so a fixture owns exactly
its own fields and teardown order stops mattering:

```python
_layers: list[dict[str, Any]] = []

def get_settings() -> Settings:
    if not _layers:
        return _load_settings()
    merged: dict[str, Any] = {}
    for layer in _layers:
        merged.update(layer)
    return _load_settings().model_copy(update=merged)

@contextmanager
def override_settings(**fields: Any):
    clashes = {k for layer in _layers for k in layer} & fields.keys()
    if clashes:
        raise RuntimeError(f"settings already overridden by an active fixture: {sorted(clashes)}")
    layer = dict(fields)
    _layers.append(layer)
    try:
        yield
    finally:
        _layers.remove(layer)      # by identity, not pop
```

`remove` by identity is the whole trick: a fixture gives back exactly its own fields regardless of what else is
active. The clash check makes contention a setup-time error instead of a silent last-writer-wins, which is the
failure mode F9 describes. Strict is the right default in tests.

Two things to note in the accessor's docstring: `get_settings()` now returns a fresh copy whenever layers are
active, so anything holding a captured `Settings` keeps the old view (only the two `assets_dir` constants do); and
the cost is one `model_copy` per call, memoizable on a layer-version counter if it ever matters.

Size S. This is the piece that makes everything else possible.

**As built.** `override_settings(**fields)` in `compose_api/config.py`, backed by a list of partial layers removed
by identity on exit. Unknown field names and a field already owned by an active layer both raise rather than
silently winning, so two fixtures overriding disjoint settings compose and two overriding the same one is an error
at the point of overlap.

#### F.b Declare the SSH dependency instead of locating it (addresses F8)

**Decision: provider injection.** Inject a `Callable[[], SSHService]` whose default is the existing global factory.

```python
SSHProvider = Callable[[], SSHService]

class SimulationServiceHpc(SimulationService):
    def __init__(self, ssh_provider: SSHProvider = get_ssh_service) -> None:
        self._ssh_provider = ssh_provider

    def _get_services(self) -> tuple[SlurmService, SSHService, Settings]:   # no longer @staticmethod
        ssh = self._ssh_provider()                      # resolved per operation, exactly as today
        return SlurmService(ssh_service=ssh), ssh, get_settings()
```

```python
class DataService(ABC):
    def __init__(self, settings: Settings | None = None,
                 ssh_provider: SSHProvider = get_ssh_service) -> None:
        self.settings = settings or get_settings()
        self._ssh_provider = ssh_provider

    @property
    def ssh_service(self) -> SSHService:
        return self._ssh_provider()                     # was: return get_ssh_service()
```

The three `self._get_services()` call sites (`simulation_service.py:72`, `:133`, `:147`) are untouched; the bare
global call at `:216` becomes `self._ssh_provider()`. The default is today's factory, so production behaviour is
unchanged and `dependencies.py:135` keeps working as written. While nearby, replace the duplicated inline
construction at `dependencies.py:175` with a call to the factory, leaving exactly one place in production that
builds an `SSHService`.

**Why a provider and not the instance.** Injecting the `SSHService` value looks simpler and matches
`SlurmService.__init__(ssh_service=...)`, but it would change behaviour. SSH resolution today is **deferred and
per-operation**: `_get_services()` runs at the top of every public method, `download_container` calls the factory
directly, and `DataService.ssh_service` is a `@property` that resolves on every access. Capturing an instance in
`__init__` would freeze that at construction time. Harmless in production, where `init_standalone()` builds
everything once and settings never change at runtime — but it converts "reads current configuration" into "pinned
at build time", which is not a change this refactor should smuggle in. A provider moves the dependency to the
boundary while leaving *when* it is read exactly as it is.

The consistency argument for value injection is also weaker than it first appears. `SlurmService` holds an
`SSHService` because it is a thin wrapper whose lifetime genuinely matches its dependency's.
`SimulationServiceHpc` and `DataService` resolve per operation. They are not the same situation.

Provider injection additionally gives a seam that value injection cannot express — a different object per
operation, for failure injection:

```python
def flaky(n: int = 1) -> SSHProvider:
    calls = itertools.count()
    def provider() -> SSHService:
        if next(calls) < n:
            raise OSError("connection refused")
        return get_ssh_service()
    return provider
```

and it is the shape pooling would slot into, which the `close()` comment anticipates: the provider becomes the
acquire step and no call site changes.

Size S. Worth doing on its own merits regardless of the backend work: it removes a service locator, deletes a
duplicated constructor, and preserves the existing resolution semantics while making the dependency visible. The
dead `set_ssh_service` line at `tests/fixtures/slurm_fixtures.py:37` goes away with it.

**As built.** `SimulationServiceHpc` and `DataService` take an `SSHProvider` (`Callable[[], SSHService]`) defaulting
to `get_ssh_service`, and resolve it per operation rather than at construction, which is what the existing design
relied on. `SSHService` gained a `port`, carried through all three `asyncssh.connect` sites, so the container's
published port reaches the production code path unchanged.

#### F.b.1 How F.a and F.b divide the work

They are complementary, and using either alone is a mistake in a different direction.

**Injection alone is a poor backend switch, because of fan-out.** Three consumers obtain SSH independently:

| Consumer | Where |
|---|---|
| `SimulationServiceHpc` | `_get_services()` at `:61`, plus a bare call at `:216` |
| `DataService` | the `ssh_service` property at `data_service.py:28` |
| `SlurmService` inside `JobMonitor` | built at `dependencies.py:175` |

A fixture that wires two and forgets the third leaves the third on real settings. In CI that is an empty key path
and a confusing failure; on a developer machine it means **talking to the production cluster while believing you
are on the container**. Injection requires knowing the full consumer list, and that list will grow.

**The settings layer is the switch.** All three resolve through `get_ssh_service()` and therefore through
`get_settings()`, so one layer reaches every consumer — including the one a fixture author forgets and the one
added next year. After F.b's de-duplication there is exactly one construction site in production reading exactly
one source with exactly one override seam, which is what makes the layer trustworthy rather than usually right.

So: **F.a switches the system, F.b is the local seam.** The e2e fixture injects nothing, because under an active
layer the default provider already yields the container descriptor:

```python
@pytest_asyncio.fixture
async def hpc_backend(slurm_cluster):
    with override_settings(
        slurm_submit_host="127.0.0.1",
        slurm_submit_port=slurm_cluster.ssh_port,       # the A4 prerequisite
        slurm_submit_user="root",
        slurm_submit_key_path=str(slurm_cluster.key_path),
        slurm_partition="cpu",
        slurm_qos="",
    ):
        yield slurm_cluster
```

Injection stays for the narrow case: handing one specific object to one service without moving the world, or the
failure-injection provider above.

**On ordering.** Because the provider is called per operation rather than at construction, the layer may be applied
at any point before the operation runs. This is the concrete reason F.b chose a provider over an instance: value
injection would have made fixture ordering load-bearing, requiring every service fixture to declare the settings
fixture as a dependency and failing confusingly when one did not. Declaring the dependency is still good practice —
it documents intent — but with a provider it is no longer a correctness requirement.

#### F.c Parameterize the backend, never the test (addresses F1, F10)

One test body. A fixture yields a backend; the backend is a parameter.

```python
def pytest_addoption(parser):
    parser.addoption("--slurm-backend", action="append", default=[],
                     choices=["container", "cluster"])

def pytest_generate_tests(metafunc):
    if "slurm_backend" in metafunc.fixturenames:
        chosen = metafunc.config.getoption("--slurm-backend") or _default(metafunc.config)
        metafunc.parametrize("slurm_backend", chosen, indirect=True, scope="session")
```

Default: `container` when Docker is present, nothing otherwise. CI gets the container without asking. A developer
on VPN runs `--slurm-backend cluster`, or passes both to run every test twice, once per backend.

**Mark by what a test needs, not where it runs.** This is the part most people get wrong: a marker called
`integration` or `e2e` answers "where does this run", which forecloses parameterization because the marker has
already chosen the environment.

| Marker | Meaning | Where it runs |
|---|---|---|
| none | no scheduler needed | everywhere |
| `@pytest.mark.slurm` | needs *a* SLURM | parameterized over the chosen backends |
| `@pytest.mark.cluster_only` | needs *the* production cluster | never in CI, never on the container |

**Differences become data, not branches.** `slurm_template_hello_TEMPLATE` currently reads
`settings.slurm_partition` and `settings.slurm_qos` directly, which is the drift surface: the container has
partition `cpu` and no QoS. One dict of fields is the single source of truth — the settings layer applies it to the
production code path, and a small descriptor exposes the same values to the test body. Maintaining those as two
separate literals would recreate the drift problem one level down.

A branch on `if backend.kind == "container"` inside a test body is the thing to forbid. That is where two
implementations quietly grow.

**Capabilities, not forked tests.** When something genuinely only works on one side:

```python
if not slurm_backend.can_build_singularity:
    pytest.skip("backend cannot build singularity images")
```

The test still exists for the other backend, the gap is greppable, and nobody writes a parallel copy.

**A conformance test is the drift alarm.** One test that runs on *every* backend and asserts the backend itself
behaves as our parsers assume: `sbatch --parsable` returns a bare integer, `squeue` emits five pipe-delimited
fields, `sacct` emits nine. Cheap, and it fails loudly when the container image and the cluster diverge — which is
otherwise exactly the kind of difference nobody notices. If both backends are available, a stronger version submits
the same job to each and compares the parsed `SlurmJob` structurally, ignoring ids and timestamps.

**What genuinely cannot be shared**, and should stay a short list: that the production partition and QoS exist and
accept work, that the real storage path under the namespace is writable, that a real Singularity build succeeds.
Those are `cluster_only` and should be smoke tests proving the environment, not tests proving logic. All the logic
lives in the shared bodies.

Size M for the fixture and the marker migration, replacing the eighteen identical `skipif` decorators. The only
production changes are F.a, F.b, and the `port` parameter from A4.

**As built.** `pytest_generate_tests` parameterizes any test reaching `slurm_backend` over the selected backends,
defaulting to `container` when Docker is present. A `cluster_only` test is restricted to the real host and, when
that is not selected, skips with a message naming the flag to pass, rather than passing silently. Eleven `skipif`
decorators became two markers: two tests run on the container, nine need real simulator images and stay
`cluster_only`. The conformance test landed as `tests/common/test_slurm_conformance.py` and immediately earned its
keep by pinning something no one had written down, that `sacct --parsable` terminates each row with the delimiter
and so yields a trailing empty field.

Differences between the backends are fields on a frozen `SlurmBackend`, so adding one is visible in review. No test
body branches on `kind`.

## Practice worth copying

- **`vivarium-workbench`'s quarantine file.** A list of known-failing test ids, deselected by a wrapper script,
  plus a non-blocking job that re-runs exactly that list and fails when an id goes stale. It exists because dead ids
  once made the watch silently run zero tests. This is how to keep a suite green without hiding the red.
- **Duration-balanced sharding.** The same repository splits 511 files four ways using recorded timings, with
  xdist inside each shard.
- **`bigraph-schema`'s matrix.** One class per type, one small method per operation. It makes a gap visible as an
  empty cell rather than as an absence nobody notices.
- **Golden vectors with an identity assertion.** Described in D3 above.

- **`viva-superpowers`'s `pypi-installable` preflight.** On every pull request it builds the wheel and installs it
  in a clean environment from PyPI *alone* — no `uv.sources`, no git — so a dependency that cannot be resolved by a
  downstream consumer fails there instead of at someone else's `pip install`. Its header documents the release that
  motivated it. See F14; the place to apply it is the client repository.
- **`viva-superpowers` pins its cross-repo golden fixture to a commit.** The upstream template checkout is pinned by
  SHA with a regenerated manifest, so an unrelated push upstream cannot redden this repository's `main`, and bumping
  it is a deliberate pull request. Directly applicable to our `pbest` pin and the generated client.
- **`viva-superpowers` tests its authored artifacts, not only its code.** Roughly twenty-eight files assert on skill
  manifests, naming conventions, a discovery contract and report linting. Our analogue is asserting `operation_id`
  stability, since those strings *are* pbest's function names and renaming one is a silent breaking change.
- **`platform`'s real-identity RBAC tests.** `backend/tests/rbac_demo/test_keycloak_integration.py` runs a
  Keycloak container preloaded with a realm defining three users at different privilege levels, fetches genuine
  tokens, and drives the real JWKS fetch, signature verification and roles extraction. A sibling file tests the same
  endpoints with auth mocked out, and each file's docstring says which layer it is. Running a fast mocked layer and
  a slow real layer over the same endpoints, and labelling them, is the shape our backend selector in F.c is
  reaching for.
- **`platform`'s `smoke.yaml`.** A genuine three-process check with no pytest: compose up Mongo and Temporal, build
  the frontend, launch both servers, then assert on `/version`, an OpenAPI path via `jq`, `/docs`, a CORS preflight,
  and that the frontend serves HTML — with log dumping on failure and teardown always. It is the only cross-service
  test in any repo here.
- **Fixture teardown that names the bug it prevents.** `platform`'s database fixtures pair the singleton restore
  with explicit data cleanup and a comment explaining that a session-scoped container would otherwise hand a later
  test a stale success record. Ours restore but do not clean.
- **Negative-authorization assertions inside the happy path.** `platform` asserts that a caller supplying someone
  else's user id gets zero rows, with a comment naming the escalation it prevents.

## Practice worth avoiding

- **Branch protection that gates on review but not on CI.** `viva-superpowers` requires an approving review on
  `main` and enforces it for admins, but declares **no required status checks at all**, so a red build does not
  block a merge. This is worse than F3's no-protection-at-all: the protection implies a gate that is not there. One
  line fixes it, and it is not ours to change.
- **Declaring Python support a matrix never exercises.** `viva-superpowers` varies operating system only while both
  legs hardcode 3.11, against a `requires-python` of `>=3.11`. One of its own modules already skips itself in CI for
  needing 3.12. Same outcome as F5 by a different mechanism, so the check to run on any repo is "does a matrix leg
  actually change the interpreter", not "is there a matrix".
- **Skipping the highest-value tests on absent private data.** `viva-superpowers`'s golden scientific studies are
  gated on workspace data CI will never have, and `pytest.skip()` on missing data is indistinguishable from passing,
  so they are green-by-absence permanently. If a test cannot run where it matters, a strict-mode environment
  variable on a scheduled job at least makes the gap visible.
- **Installing a coverage plugin and never invoking it.** `pytest-cov` is a declared dev dependency there and
  appears in no command, which reads as coverage being handled when it is not measured at all.
- **`biosim-client`'s ungated live calls.** Its CI hits the production API on every matrix leg, and one test
  asserts a hard-coded remote version string, so a server release breaks the client's build.
- **`platform`'s release path.** `release.yaml` builds and pushes three container images and cuts a GitHub Release
  with **no test dependency** — its only guard compares the tag against a version file. Nothing re-runs the suite
  at the tag. Our own `build-containers.yml` has the same property.
- **Documenting a command that cannot run.** Two `platform` documents advertise `uv run pytest --cov=biosim_server`
  while `pytest-cov` is absent from the lockfile. A reader's first attempt fails, which teaches them the docs are
  unreliable.
- **`compose-server`'s state.** Seven workflows, all manual; the one test job invokes a file that does not exist;
  a test module runs a real dispatch at import time. It is the end state of not deciding.

## How this document is meant to be used

Part 1 and Part 2 should be corrected wherever they are wrong; they are measurements and they will age. Part 3 is
where the argument happens. The next step is to pick from A through E, which is a plan-mode conversation, not an
edit to this file.
