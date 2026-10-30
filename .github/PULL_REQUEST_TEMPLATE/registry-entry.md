<!-- For a PR that adds or changes an entry in compose_api/registry/manifest.yaml. Open it with `?template=registry-entry.md`
     on the compare URL. Guide: https://github.com/biosimulations/compose-api/blob/main/docs/registry-onboarding.md -->

## What this changes

- Entries in this PR: id, `kind`, source repository. A component's `requires` libraries are entries too; they install code as
  root, though a library's level gates nothing. Repeat the items below for each.
- In your shell, `R` = owner/repo, `C` = the pinned commit (for `pypi`, the release's tag commit, or say it names none) and
  `B` = its default branch. The commands need `gh`, `jq` and `git`.
- New entry, new pin, new install or conda, or level change. For a new pin: the old pin, and the files changed since it
  (`gh api repos/$R/compare/<old>...$C --jq '.files|map(.filename)'`):
- Level asked for (`listed`, `installable`, `tested`, `validated`, `curated`):

## The entry

Preferred: generate it with `vivarium-workbench compose-entry` and paste its output and its check result. A hand-written
entry is accepted: say so, and say why.

```yaml
```

Check result (paste it in a fence):

## Trust and provenance (what is trusted is the commit `C`, not the repository)

- [ ] Who controls `R` (`gh api repos/$R --jq '.owner.login,.owner.type,.default_branch'`) and who authored commits on `B` lately
  (`gh api "repos/$R/commits?sha=$B&per_page=15" --jq '[.[].author.login]|unique'`):
- [ ] `C` (`install.commit` for `git`) is a full 40-character hash on `B`: `gh api repos/$R/compare/$B...$C --jq .status` prints
  `identical` or `behind`; or a release tag's: `gh api --paginate repos/$R/tags --jq ".[]|select(.commit.sha==\"$C\").name"`
  prints the tag. Any `commit:` or `source:` in the entry names the same repository and hash as `install`.
- [ ] Install-time code runs as root in the build. Listed here: the build backend, `build-system.requires`, and any `setup.py`,
  `cmdclass`, build hook or build script (`gh api -H 'Accept: application/vnd.github.raw' "repos/$R/contents/pyproject.toml?ref=$C"`).
  For `pypi`, the release's files, since without a wheel for the environment's Python on linux-64 its sdist builds here
  (`curl -s https://pypi.org/pypi/<name>/<version>/json | jq '[.urls[].filename]'`); for `url`, how the wheel was built.
  `[project].name` at `C` is the name `install` derives (the repository's name for `git`); the generated `pixi.toml` uses it:
- [ ] Runtime dependencies (`[project].dependencies` and the `install.extras` it selects) are listed here. None is dev tooling
  (`vivarium-workbench`, `viva-superpowers`, `pbg-superpowers`, test or lint tools), none is a git or URL reference, and
  `requires-python` and the `process-bigraph` and `bigraph-schema` bounds admit the versions in `environments.yaml`, or the PR says why:
- [ ] No class imports or runs a module, command or URL named in its config; the address check sees only `address`. In a clone:
  `git grep -nE 'import_module|__import__|subprocess|os\.system|pickle|urlopen|requests|eval\(|exec\(' $C -- ':(glob)**/<module root>/**'`

## Fields

- [ ] `module_roots` contains every top-level package whose classes documents will name, taken from what the build backend ships
  (hatch or setuptools `packages` or `packages.find`, maturin `module-name`) in the same `pyproject.toml`, not from the repository
  name and not copied from `catalog.yaml`. Each is a package directory at `C`:
  `gh api "repos/$R/git/trees/$C?recursive=1" --jq '.tree[].path' | grep -E '(^|/)<root>/__init__.py$'`
- [ ] No root is a generic name (`app`, `src`, `utils`), and none lies inside or around another entry's, since the longest root
  wins (`grep -n -A3 module_roots: compose_api/registry/*.yaml`). Any other top-level package the wheel ships is listed here,
  with what it does on import (discovery imports every installed package that requires `bigraph-schema`):
- [ ] What PyPI cannot supply (Node.js, MPI, a C++ engine) is under `conda:`, compared with the repository's own `pixi.toml` or
  `environment.yml` if it has one. A package another entry also lists has the same spec (`grep -n "<package>:" compose_api/registry/manifest.yaml`).
- [ ] `requires` lists the engines the package imports but does not declare. Each `types` item (`module:attribute`) is in this
  entry's own package; the runner imports it before every run. `bundles` is empty (a mash-up needs no `environments.yaml`
  line), or names an environment already in `environments.yaml` (a composed one lists the entry; a prebuilt image lists none).

## Evidence and compliance

- [ ] `evidence` says what supports the level asked for, and which commit it is about.
- [ ] Compliance case path, `compose_api/registry/compliance/<entry>/<case>/case.yaml`; where its expected values come from
  (hand calculation, reference file, an independent implementation, the package's own earlier output); or why there is no case:
- [ ] The case is found and its files exist. This prints `[('<case>', [])]`; `[]` alone means no case was found. A case that
  cannot run is skipped with a warning and the entry keeps its manifest level:
  `uv run python -c "from compose_api.environments.compliance import case_problems, load_cases; print([(c.name, case_problems(c)) for c in load_cases('<entry>')])"`
- [ ] No Step output port type adds or appends (`float`, `integer`, `array`, `list`, `set` and the like, also inside `map[...]`);
  use `overwrite[...]`. Processes are exempt; a named type is judged at read-back. In a clone:
  `git grep -n -A12 'def outputs' $C -- ':(glob)**/<module root>/**'`
- [ ] CI is green. Locally: `uv run python -m pytest tests/registry tests/environments/test_compliance.py -q` (needs Docker)
