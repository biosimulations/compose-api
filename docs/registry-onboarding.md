# Adding a simulator to the registry

In `registry_env` and in every composed environment (mash-ups included), compose-api runs a process class only if its module
belongs to an entry at level `tested` or higher, as set in `compose_api/registry/manifest.yaml` or as computed from the
compliance cases of the composed version (`registry/validation.py`). A prebuilt image's classes are not looked up: an
administrator vouches for the image by registering it as a version (`api/routers/simulation.py`). This page is for anyone who wants a wrapper
repository (a `viva-*` workspace, or any process-bigraph package) to run here, and for the person who reviews that change. The
checklist is the pull request template
[`registry-entry.md`](https://github.com/biosimulations/compose-api/blob/main/.github/PULL_REQUEST_TEMPLATE/registry-entry.md);
this page says what it asks for and why.

GitHub fills a pull request from a template in a `PULL_REQUEST_TEMPLATE/` directory only when the compare URL names it:
`https://github.com/biosimulations/compose-api/compare/main...<branch>?quick_pull=1&template=registry-entry.md`
([GitHub: query parameters](https://docs.github.com/en/pull-requests/reference/using-query-parameters-to-create-a-pull-request)).
Opened any other way, paste the template's text into the description.

## Three paths

1. **Listed through viva-catalog. This never runs.** `registry/catalog.py` reads viva-catalog's `modules.json` and writes
   `registry/catalog.yaml`: every wrapper at level `listed`, pinned to the commit its branch pointed at that day. The file is
   generated and never edited by hand. The service runs `tested` or higher, so admission refuses a listed entry's classes.
   Listing makes a repository discoverable and grants nothing.
2. **A manifest entry, by pull request, at the level the evidence supports.** The entry names the package, how it installs, the
   modules it provides and the evidence for its level. Entries change only by pull request, and an entry in `manifest.yaml`
   takes precedence over the `catalog.yaml` entry with the same id. Administrators register environment versions through the
   API, never entries.
3. **After the merge**, below: a release, then a signed-in run builds the environment.

## After the merge

- The manifest is a versioned file in the package, read at call time, so an entry takes effect with the next compose-api release.
- An entry with empty `bundles` is in no declared environment. When nothing covers the entries a document names, the first run by
  a signed-in caller makes a mash-up of exactly those entries, with what they `requires`: a `pixi.toml` generated from the
  entries, locked in an unprivileged Job, built on the privileged builder, read back, and checked by each member entry's
  compliance cases (`docs/plan-environment-composition.md`, D7.4, D7.5). Later runs with the same set reuse that version.
- An anonymous caller whose run needs a mash-up that does not exist gets a 401 and causes no build. At most two are locked or
  built at once, and a set of packages that conflict is a 409 with pixi's explanation (`environments/lifecycle.py`). If the first
  lock or build of a set fails, later runs of that set get a 409 until an administrator makes a new version.
- The cases decide the entry's level in that version: `tested` when they pass, `failed` when one does not, `untested` without
  cases. An entry with no cases, with cases still running, or whose cases cannot run (a missing file is a logged warning) keeps
  the manifest's level for admission (composition plan, 5b, 5c; `environments/compliance_runs.py`).
- Moving the pin is another manifest pull request and release; a pin that moves never starts a build by itself (D7.7).
- A package that publishes its own image is registered by an administrator as a version of a named environment (D8.3), which
  needs its own line in `environments.yaml`.

## Writing the entry

Preferred: generate it with `vivarium-workbench compose-entry`, which produces the entry and checks it (see its `--help`), and
paste both into the pull request. A hand-written entry is accepted: copy the closest one in `manifest.yaml` and say in the pull
request that it is hand-written, and why. By shape: `viva-basic-processes` (git, nothing else), `pbsim-common` (git with
`requires` and `types`), `viva-pde-particle` (git with `conda:` engines, extras, and its own image), `pb-multiscale-actin` (a
PyPI release), `smoldyn-vcell` (a wheel by URL and `sha256`).

A component often needs library entries beside it (`kind: library`: an engine, or a pin on a floating dependency; `install` or
`conda`, no `module_roots`). They install code like any other entry and are reviewed the same way. Their level gates nothing:
what runs is a component's classes (`environments/lifecycle.py`, `composable`).

## Check that it locks

A signed-in first run of an entry makes a mash-up of exactly that entry and what it `requires`: `pixi_toml()` writes a pixi workspace,
an unprivileged Job locks it with `pixi exec --spec git -- pixi lock` in the image `environments.yaml` names, and a lock that does not
resolve is recorded as a failed version. Later runs of that entry set then get a 409 until an administrator makes a new version
(`environments/service.py`, `environments/lifecycle.py`), so an entry that cannot lock must not reach a release at `tested`, and no check
above locks one. To run the same step before asking, in a clone of compose-api whose `manifest.yaml` has the entry (an entry that is only
in `catalog.yaml` has no `install`, so there is nothing to lock):

```bash
ENTRY=viva-ketchup      # the entry's id
W=$(mktemp -d)
uv run python - "$ENTRY" > "$W/pixi.toml" <<'PY'
import datetime
import sys

from compose_api.environments.pixi import DEFAULT_PYTHON_VERSION, ComposedSpec, pixi_toml
from compose_api.registry.environments import load_environments
from compose_api.registry.manifest import load_manifest

composition = load_environments().composition
entry = next(e for e in load_manifest().entries if e.id == sys.argv[1])
now = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
spec = ComposedSpec("lock-check", (entry,), tuple(sorted(composition.core.items())), composition.platform, DEFAULT_PYTHON_VERSION, now)
print(pixi_toml(spec), end="")
PY
IMAGE=$(uv run python -c 'from compose_api.registry.environments import load_environments; print(load_environments().composition.pixi_image)')
docker run --rm --platform linux/amd64 --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$W":/work -w /work "$IMAGE" pixi exec --spec git -- pixi lock
grep '^- pypi: git+' "$W/pixi.lock" | grep -v '?rev='     # git sources pinned to no commit; empty is what is wanted
```

`--platform linux/amd64` is the Job's platform (on Apple silicon the arm64 image fails whenever a source build is needed); `HOME=/tmp` keeps
pixi's cache inside the container (on macOS a cache on the mounted folder fails with "failed to link ... Invalid argument"). What a lock
does not show: the privileged build, the run, this entry together with others, or a later day (`exclude-newer` is now, and a git branch
tip moves).

## What CI checks

These run on every pull request, so a change that breaks one is red before a reviewer reads it:

- An entry is pinned by `version` or `commit`, has `module_roots` if it is a component, and ids are unique (`registry/manifest.py`).
- An `install` names exactly one of `pypi` with its exact `version`, `git` with a full 40-character `commit` (never a branch), or
  `url` (an https `.whl`) with its `sha256`. `requires` names entries that exist.
- Every entry above `listed` has `evidence`, and every library says how it installs (`tests/registry/test_manifest.py`).
- Each declared environment still composes: no two entries install one distribution, no conda package is asked for with two
  specs, `requires` are listed, `bundles` and `entries` agree (`registry/environments.py`, `tests/registry/test_environments.py`).
- Compliance cases are checked only for the entries a test names, today `pbsim-common`, `viva-basic-processes` and
  `viva-pde-particle` (`tests/environments/test_compliance.py`). No test walks every entry's cases, so a new entry's case is
  checked only by a test its pull request adds or by the reviewer, with the command in the template.
- Whether an entry's environment locks is checked by none of these (see "Check that it locks").

Locally: `uv run python -m pytest tests/registry tests/environments/test_compliance.py -q` (the database-backed tests need
Docker), and `make check` for the lint and type checks (`CLAUDE.md`).

## What only a reviewer can check, and why

- **Provenance.** An entry is pinned to a release or a commit (composition plan, "What is a safe component"). The reviewer approves
  that commit, not the repository, so the template asks who controls the repository, that the hash is on its default branch or a
  tag, and, for a new pin, which files changed since the old one. A commit on the default branch or a tag is also the test
  `plan-entry-updates.md` proposes for moved commits.
- **One hash, one repository.** Only `install.commit` is validated, and it is what pixi installs (`environments/pixi.py`).
  `commit:` and the `source` URL are what people read, and nothing ties them to `install`: not the hash, nor the repository.
- **Install-time code.** The build runs package code as root on the privileged builder, and locking reads package metadata, which
  can run build code, in an unprivileged Job (`simulation/build_k8s.py`). The reviewer reads the build backend, its requirements
  and any `setup.py`, hook or build script. A `pypi` pin is built too when the release has no wheel for the environment's Python,
  and for a `url` pin the reviewer asks how the wheel was built (the `smoldyn-vcell` entry names the workflow that built it).
- **Import-time code.** process-bigraph builds its core with bigraph-schema's `allocate_core`, which imports the modules of every
  installed distribution that requires `bigraph-schema` (bigraph-schema 1.8.1, `package/discover.py`: `is_process_library`,
  `load_local_modules`). Import-time code in anything a wheel ships, and in every dependency that requires `bigraph-schema`, can
  therefore run whether or not a document names it. That is why the template asks about packages outside `module_roots`.
- **Distribution name.** The generated `pixi.toml` keys the dependency by the name `install` derives (the repository's name for
  `git`), and two entries with one name are a composition problem. `[project].name` at the commit should be that name.
- **Dependencies.** A composed environment installs the package's declared dependencies, so a development tool among them lands in
  every run image, and a git or URL reference is not covered by the pin. The pin freezes the package, not what it depends on:
  those resolve when the version is locked, no newer than the lock's `exclude-newer` date (`environments/pixi.py`). The
  composition also fixes Python and the core's `process-bigraph` and `bigraph-schema` versions (`environments.yaml`), so a
  package whose bounds exclude them cannot be locked with the others. viva-pde-particle keeps `vivarium-workbench` behind a `workbench` extra for this
  reason (its `pyproject.toml`). A git package's own `[tool.uv.sources]` are followed as well: a source that sends a dependency to a
  branch pins nothing, and the lock takes that branch's tip, and the tip's own sources, the day it runs ("Check that it locks"
  lists them).
- **Config-driven imports.** The address check is the only gate (`registry/validation.py`) and sees only `address` values. A class
  that imports or runs what its config names escapes it: `EnsembleRunner` imported a `module:function` from its config, and
  viva-pde-particle#67 replaced it (composition plan, 7c-4). The `types` items are imported by the runner before every run
  (`environments/runner.py`), so each should be in the entry's own package.
- **Module roots.** Admission gives a module to the entry with the longest matching root and refuses a module no root contains
  (`Manifest.entry_for_module`). A root that is not what the package ships makes its own classes unrunnable, a generic root such
  as `app` claims every module beneath it, and a root nested inside another entry's takes classes from it; nothing compares one
  entry's roots with another's (`Manifest` validates ids and `requires`). `catalog.yaml`'s roots come from viva-catalog's
  `package` field, which `registry/catalog.py` copies without checking. Many of them do not match what the repository
  ships: a workspace whose package is `pbg_<x>` is recorded as `viva_<x>`, `viva_Mgen` is listed for a package that ships
  `viva_mgen`, and some omit a package the workspace also ships (a compatibility shim or a studies package). Take the roots from what the build backend ships
  (hatch or setuptools `packages` or `packages.find`, maturin `module-name`), not from the repository's name. A directory that
  exists in the tree is not proof that the wheel ships it: read the packaging settings.
- **Non-Python needs.** What PyPI cannot supply (a Node.js bridge, MPI, a C++ engine) belongs under `conda:`. Two entries that list
  one conda package with different specs cannot share an environment: a mash-up of them is refused with a 409 at run time, and CI
  checks only the declared environments (`registry/environments.py`).
- **Step outputs.** `step-outputs-replace` refuses a Step whose output ports add or append (`float`, `integer`, `array`, `list`,
  `set` and the like, also inside `map[...]`; `environments/compliance.py`). It runs when a built version is read back, so a Step
  that fails it is found only after the merge and costs a second pull request (viva-pde-particle#69, then a new pin). Reading its
  `outputs()` first avoids that.
- **Evidence and the case.** `evidence` says what supports the level, and which commit it is about. The case's `description` should
  say where its expected values come from: a hand calculation (`viva-basic-processes`), a reference report (`pbsim-common`), or
  the package's own earlier output run through compose-api's runner (`viva-pde-particle`). `load_cases` returns an empty list for a
  directory it does not find, which looks the same as "no case", so the template's command prints each case with its problems.

## Levels

The service runs a component whose level is `tested` or higher, as the manifest sets it or as a composed version computed it from
the entry's cases (`HPC_MINIMUM_LEVEL`, `registry/validation.py`); `listed` and `installable` components do not run. Raising a
level needs its evidence in `evidence` (the header of `manifest.yaml`). `validated` and `curated` need more, set out in
`docs/strategy.md`, decision 5. Ask for the level the evidence supports and say which evidence it is; the reviewer decides.
