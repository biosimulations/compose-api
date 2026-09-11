# Testing plan: current state and candidate actions

**Status:** working document, opened 2026-09-11. Part 1 and Part 2 are findings, measured on that date and meant to
be checkable. Part 3 is a menu of candidate actions with sizes and costs, not a decided plan. Nothing here has been
agreed; the decisions get made by iterating on this file.

**Scope.** This repository (`compose-api`) and `pbest` are the subjects. The other repositories in the loop are
included as context and as sources of practice worth copying or avoiding: `sms-api`, `biosim-client`,
`compose-server`, `process-bigraph`, `bigraph-schema`, `spatio-flux`, `pbg-vcell-fvsolver`, `vivarium-workbench`.

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

Actual coverage here is **45%** against a stated target of 90%, and no pull request carries a codecov status check.
The worst-covered modules are the ones the HPC gate hides: `slurm_service` at 18%, `job_monitor` at 20%,
`ssh_service` at 23%, `handlers` at 19%.

### F3. Neither repository has branch protection

`gh api repos/biosimulations/compose-api/branches/main/protection` returns "Branch not protected", and so does
pbest's. Every check on every pull request in both repositories is advisory. A red pull request can be merged, and
a direct push to `main` is possible.

`pbest/CLAUDE.md` states that `main` "is protected: no direct pushes, changes land through a PR". That is not true
today, and a stale instruction is worse than none because it stops people checking.

### F4. This repository runs its CI twice

`.github/workflows/main.yml` and `.github/workflows/ci-test.yml` are both named "Main" and both define `quality`,
`tests-and-type-check`, and coverage steps. One triggers on pull requests and pushes to `main`; the other on every
push to any branch. On a pull request branch both fire.

That is why every pull request shows two `quality` jobs and seven `tests-and-type-check` jobs. Roughly half the CI
minutes spent on this repository are duplicate work, and the duplication also explains why the codecov condition
appears twice with different matrices.

### F5. The Python matrix does not test Python versions

The composite action installs an interpreter with `setup-python`, then runs `uv sync`, which ignores it and uses
`.python-version` instead. A CI log from this week shows both lines:

```
Successfully set up CPython (3.12.14)
Using CPython 3.14.7
```

All seven matrix legs execute the same interpreter. The matrix costs seven times the minutes and proves nothing
about version compatibility. The same is true in every repository here that has a matrix.

### F6. The risk profile is inverted

The pure library with no I/O is exhaustively tested: `bigraph-schema` has about 1,178 tests, no gating, and a
systematic type-by-method matrix where each schema type gets a class and each method a cell. Everything runs in CI.

The distributed system with SSH, SLURM, Postgres, NATS, and container builds runs nine tests.

Two repositories in the composition path have effectively nothing. `spatio-flux`, the demo library named in the
paper, has no suite at all; its `tests.py` is a demo script with no assertions and four of seven demos commented
out of its own entry point. `pbg-vcell-fvsolver` has nine genuinely good numerical tests, including mass
conservation to 2%, and no CI to run them.

### F7. Smaller things worth fixing while nearby

- `tests/simulation/dont_test_sedml.py` (3 tests) and 12 commented-out tests in pbest are dead weight. Either
  restore them or delete them, but leaving them as text misleads.
- `pbest`'s CI has no `pull_request` trigger, so its checks never appear on a pull request.
- `pbest` measures coverage and discards it.
- `process-bigraph`'s REST and Ray transports are covered only by `slow` tests that CI never enables, so those
  transports are untested in every realistic environment. Relevant to us because the composition protocol's remote
  story rests on them.

---

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
4. **Containerized SLURM in a testcontainer.** Size **S–M**, and no longer speculative: measured working against
   this repository's own code on 2026-09-11. See A4 below.
5. **Do nothing, but say so.** Document that the HPC path is covered by manual testing only, and stop implying
   otherwise with a 90% coverage target. Size S.

#### A4 in detail: measured, not estimated

Everything in this subsection was run, not reasoned about. The image is `xenonmiddleware/slurm:latest`, started as
a plain container with port 22 published, a generated public key injected into the `xenon` user's
`authorized_keys`, and then driven through **this repository's real `SSHService` code path and `SlurmJob`
parsers** — not through a separate SSH client written for the test.

Result, verbatim:

```
asyncssh key auth: OK
sbatch --parsable -> '3'  (int-parseable: True)
squeue raw: '3|wrap|(null)|xenon|PENDING'
  parsed squeue -> job_id=3 name='wrap' user='xenon' state='PENDING'
sacct raw: '2|wrap|(null)|xenon|COMPLETED|2026-09-11T18:11:59|2026-09-11T18:12:01|00:00:02|0:0|'
  parsed sacct  -> job_id=2 state='COMPLETED' start='2026-09-11T18:11:59' end='2026-09-11T18:12:01'
                   elapsed='00:00:02' exit='0:0'
scp_upload: OK
sbatch of uploaded file -> 4
```

Those are the exact commands `SlurmService` issues: `squeue -u $USER --noheader --format="%i|%j|%a|%u|%T"` and
`sacct -u $USER --parsable --allocations --delimiter="|" --noheader --format="jobid,jobname,account,user,state,
start,end,elapsed,exitcode"`. The output parsed cleanly through `SlurmJob.from_squeue_formatted_output` and
`from_sacct_formatted_output`.

**`sacct` was the open question and it works.** `sacct` needs the accounting daemon, which many minimal SLURM
images do not run; this one does (its startup log says "making accounting readable to users"). Without it, only
`squeue` would be exercisable and the `sacct` reconciliation path in `JobMonitor` would stay dark.

**What it covers.** `sbatch --parsable`, both status-parsing paths, `scp_upload`, real job state transitions
(`PENDING` → `COMPLETED`), and the sbatch heredocs in `simulation_service.py` actually executing. That is
precisely the code the HPC gate hides today: `slurm_service` 18%, `handlers` 19%, `job_monitor` 20%,
`ssh_service` 23%.

**What it does not cover.** Neither `singularity` nor `apptainer` is present in the image, so the container-build
job path (`singularity build --fakeroot`) stays uncovered by this route. Partition and QoS names are the
container's (`mypartition`, `otherpartition`), not the cluster's.

**One prerequisite code change.** `SSHService.__init__` accepts hostname, username, key path, and known hosts —
**there is no port parameter**, and none of its three `asyncssh.connect` call sites passes one, so it can only
reach port 22. A testcontainer publishes a random high port. Adding `port: int = 22` and threading it through
those three calls is the whole change, and it is defensible on its own merits.

**Two corrections to the obvious first draft of such a fixture.** Use `asyncssh` with an injected key rather than
`paramiko` with the image's default password: the point is to exercise `SSHService`, and a `paramiko` client would
test `paramiko`. And poll `sinfo` until it answers rather than sleeping a fixed interval; the image carries a
Docker healthcheck and cold start measured **one second** under amd64 emulation on an arm64 laptop.

**The real caveat: the image is old.** `xenonmiddleware/slurm:latest` is **SLURM 17.02.6, published March 2020,
amd64 only**. Pinning our parsers against a six-year-old output format is a genuine cost, mitigated by the fact
that these particular format strings have been stable across those releases. Before adopting, check what version
the cluster runs. `giovtorres/slurm-docker-cluster` is actively maintained (last update August 2026) and is the
better-known option, at the cost of being a multi-container compose cluster rather than one image.

**Suggested shape if this is chosen.** A session-scoped fixture that starts the container, injects a generated
key, waits on `sinfo`, and yields a real `SSHService` pointed at the mapped port. The existing `skipif` gate then
changes meaning: instead of "skip unless a cluster credential exists", it becomes "use the real cluster when a
credential exists, otherwise use the container". Same tests, two backends.

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

### E. Tidy (addresses F7)

Restore or delete the dead tests; add a `pull_request` trigger to pbest; upload or stop measuring pbest's coverage.
Size S in total.

---

## Practice worth copying

- **`vivarium-workbench`'s quarantine file.** A list of known-failing test ids, deselected by a wrapper script,
  plus a non-blocking job that re-runs exactly that list and fails when an id goes stale. It exists because dead ids
  once made the watch silently run zero tests. This is how to keep a suite green without hiding the red.
- **Duration-balanced sharding.** The same repository splits 511 files four ways using recorded timings, with
  xdist inside each shard.
- **`bigraph-schema`'s matrix.** One class per type, one small method per operation. It makes a gap visible as an
  empty cell rather than as an absence nobody notices.
- **Golden vectors with an identity assertion.** Described in D3 above.

## Practice worth avoiding

- **`biosim-client`'s ungated live calls.** Its CI hits the production API on every matrix leg, and one test
  asserts a hard-coded remote version string, so a server release breaks the client's build.
- **`compose-server`'s state.** Seven workflows, all manual; the one test job invokes a file that does not exist;
  a test module runs a real dispatch at import time. It is the end state of not deciding.

## How this document is meant to be used

Part 1 and Part 2 should be corrected wherever they are wrong; they are measurements and they will age. Part 3 is
where the argument happens. The next step is to pick from A through E, which is a plan-mode conversation, not an
edit to this file.
