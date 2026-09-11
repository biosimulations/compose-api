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

### F7. One of the nine tests that run in CI is flaky

`tests/common/test_nats.py::test_sync_producer_with_async_subscriber` failed on pull request #161, a docs-only
change, with:

```
AssertionError: assert b'hello world 5' == b'hello world 9'
```

It is a race between the synchronous producer and the asynchronous subscriber, not a regression. The proof is that
the duplicated CI (F4) ran the same commit twice on the same Python: one leg passed and the other failed. It also
passes locally three times out of three.

This matters more than it looks. Only nine tests execute in CI (F1), so a single flaky test is an eleven percent
false-failure rate on the entire signal. Combined with the absence of branch protection (F3), the practical effect
is to train people to merge past red checks, which is precisely the habit that makes a suite worthless.

### F8. The dependency-injection pattern has a hole at SSH

`compose_api/dependencies.py` provides `get`/`set` pairs for five services: the postgres engine, database service,
simulation service, job monitor, and data service. Fixtures save, swap, yield, and restore each one. That part
works and is the strongest thing in the suite (§1.3).

**SSH is not one of them.** There is no `set_ssh_service` anywhere in the codebase. What exists is a factory in
`compose_api/common/ssh/ssh_service.py:111` that rebuilds from settings on every call:

```python
def get_ssh_service() -> SSHService:
    settings = get_settings()
    return SSHService(...)
```

Three production call sites use it: `simulation_service.py:61`, `simulation_service.py:216`, and
`data_service.py:28`.

The consequence is that the `ssh_service` fixture yields an object **only the test code ever sees**. It is passed
directly to `SlurmService` in the test body. As soon as the test exercises `SimulationServiceHpc`, that code calls
`get_ssh_service()` and builds a fresh connection from settings, ignoring the fixture entirely.

The evidence that someone hit this and worked around it is in the fixture itself: `tests/fixtures/slurm_fixtures.py:37`
contains a commented-out `set_ssh_service(saved_ssh_service)` calling a function that does not exist.

This is why A6 below routes through settings rather than through injection. For the SLURM path, settings are not
merely convenient; they are the only lever.

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

### F10. Smaller things worth fixing while nearby

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

### E. Tidy (addresses F7, F10)

Fix the `test_sync_producer_with_async_subscriber` race (wait on the subscriber rather than assuming ordering);
restore or delete the dead tests; add a `pull_request` trigger to pbest; upload or stop measuring pbest's coverage.
Size S in total. The flake is worth doing first and on its own: while only nine tests run in CI, one unreliable
test is an eleven percent false-failure rate on the whole signal.

---

### F. One test body, two backends (addresses F1, F8, F9)

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

#### F.b Close the SSH injection hole (addresses F8)

Either add `set_ssh_service` to `dependencies.py` so SSH joins the other five services, or accept that settings are
the injection point and delete the misleading commented-out line at `tests/fixtures/slurm_fixtures.py:37`. The
second is cheaper and, given F.a, sufficient. The first is more consistent with the rest of the file. Size S
either way; the choice is about consistency, not capability.

#### F.c Parameterize the backend, never the test

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
production changes are F.a, the `port` parameter from A4, and optionally F.b.

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
