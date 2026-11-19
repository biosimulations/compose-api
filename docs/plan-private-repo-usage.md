# Private workspace repositories on compose-api (first case: vivarium-collective/v2ecoli)

**Status (2026-11-19): approved; P0 next.** A private viva workspace repository is onboarded (a registry entry and an
environment) and used (run, status, results) on compose-api, with v2ecoli as the first case of a general mechanism.
Checked against `main` at `53db5d9` (#547 merged). One PR per step, each merged with a merge commit; deploying is a
release, one at a time, as usual.

| Phase | What | State |
|---|---|---|
| P0 | Outreach (Auth0, design review, v2ecoli) and three probes; no code | next |
| P1 | compose-api: restricted entries, gates and the disk fix (A, B) | — |
| P2 | compose-api: fetching private source (C) | — |
| P3 | Prove it live on a tiny private probe repository | — |
| P4 | v2ecoli readiness (v2ecoli PRs) | — |
| P5 | Onboard and use v2ecoli | — |
| P6 | Docs | — |

## Context

- **v2ecoli is private**; all of its dependency repositories are public. compose-api's repository is **public**.
- **No credential path exists.** Lock, uv-lock and build Jobs (`compose_api/simulation/build_k8s.py`) fetch git
  anonymously and mount no secret. The build service account may not touch Secrets (`kustomize/base/rbac-builds.yaml`).
- **Built images stay on HPC storage** as SIFs (`hpc_utils.py`), never pushed. **But that storage is readable to other
  users:** `job_script.py:70,89,97` chmod run outputs and inputs `a+r`, `staging.py:25-26` writes 0644/0755, and SIFs
  copy with the pod's umask. Anyone who can traverse `/projects/CRBM/compose_api/<ns>` could read v2ecoli's code and
  runs.
- **No per-entry or per-environment access control.** About 20 registry, results and core routes serve entries,
  environments, manifests, locks, failure text, compliance and build logs to anyone. Anonymous callers can start builds
  and are routed into existing mash-ups. Compliance runs have no owner, so they are public. `readable_clause`
  short-circuits for admins before any other rule (`authorization.py`).
- **v2ecoli cannot be locked yet** (separate from credentials):
  - Python `==3.12.12` (vEcoli `==3.12.9`) vs compose-api's `3.12.*`;
  - its `[tool.uv.sources]` float on `main`, and process-bigraph and bigraph-schema then clash with the core's 1.9.1
    and 1.8.1;
  - the ParCa blob and cache builder are not in the wheel;
  - no saved document uses full `local:module.Class` addresses;
  - its Cython needs a compiler.

  Eran (eagmon) owns the repository.

## Decisions (2026-11-19)

1. **The access list is an Auth0 role per private repository.** The entry names the role, and the members are the
   tenant users who hold it. There is **no admin bypass**: an operator who needs access is given the role.
   - Auth questions go to Nov. compose-api design review goes to Jim.
   - The v2ecoli members are people who have not signed up yet (P0).
2. **Entry metadata may be public**: repository URL, commit, module roots, and a compliance case that is a document
   only. Code, images, locks, interfaces, failure text and runs stay private: hidden by the API and unreadable on disk.
3. **v2ecoli is composed from git**, not a prebuilt image. The mechanism is proven first on a tiny private probe
   repository, so it does not wait on v2ecoli's readiness.

## Design

### A. Restricted entries

- A manifest entry gains an optional `access_role: <name>` (`registry/manifest.py`; not empty, not `user`).
- `create_composed` (`environments/service.py`) records the version's roles in its spec (`spec["access_roles"]`).
  Everything about a version and its runs then uses those recorded roles, so a later manifest edit can't narrow them.
  Changing an entry's role means a new version. Runs from before a role was added stay as they were (documented).
- **CI rules** (`tests/registry/`). A restricted entry:
  - is never in a shared or `core` environment, `solvers.yaml`, or a suite;
  - is never in an unrestricted entry's `requires`;
  - has no `module_roots` overlapping another entry's, and no `alternative_to`;
  - has a compliance case that is a document only;
  - is `tested`, which is required to be composable (`lifecycle.py:142`).

  This keeps SED-ML, suites, sources, curated runs and comparisons out of scope.
- One predicate in `compose_api/authorization.py`, `may_use(caller, roles)`: true when `roles ⊆ caller.roles`. An
  anonymous caller never passes a non-empty set.

### B. Gates

- **Submission** (`api/routers/simulation.py`). The caller's manifest is the manifest minus the entries they may not
  use. It is passed to `validate_submission` (a new parameter; today it loads the full manifest itself),
  `unregistered_violations` and `needed_entries`.
  - A non-holder gets the same 400 as for an unregistered class, on the inferred and the named paths alike.
  - `covering_environment` never picks an environment whose roles exceed what the needed entries require.
  - Naming a restricted environment without the role gets the unknown-name 400.
- **Registry and other routes.**
  - Gate the helpers the routes share: `_known_kind`, `_offered_interfaces`, `_simulator` and `_simulator_uses`
    (`registry.py`).
  - Filter `list_environments`, `/registry/entries`, `/core/simulator/list` (`compute.py`), build status and log
    (`results.py`), and the `environment=` / `environment_version=` filters (`simulations.py`).
  - The admin routes (create version, inspect, default, retire, compliance POST) also answer 404 without the role.
  - Unknown and forbidden look the same.
  - `Vary: Authorization` on gated responses, and `useRegistry.ts` drops its cache when the sign-in changes.
- **Runs.**
  - A new column `simulation.access_roles TEXT[] NOT NULL DEFAULT '{}'`, added by an idempotent alembic revision. It
    is stamped in `handlers.run_simulation`, the single funnel, so compliance runs get it too.
  - `can_read` and `readable_clause` apply the role gate first, before the owner/visibility rule and before the
    `_is_admin` shortcut. Datasets, events, traces, comparisons and favorites inherit through them.
  - "Public" on a restricted run means every role holder, never anonymous.
- **Disk.** The fix follows the P0 permissions probe. Expected: no "other" access at `<store>/<ns>`, relying on a group
  the API user (16997/10000) and the SLURM user share. Without one, an HPC admin creates that group.
- **Accepted and documented:** the build-concurrency 429 and queue positions count restricted work.

### C. Fetching private source

- **A GitHub App,** created under `biosimulations` by an owner of both organizations, with Contents read-only and no
  webhooks.
  - It is installed on `vivarium-collective` for selected repositories only: v2ecoli and the probe repository.
  - Its key is the SealedSecret `github-app` in `kustomize/overlays/compose-api-rke`, made by a new
    `kustomize/scripts/sealed_secret_github_app.sh` copied from `sealed_secret_ghcr.sh`.
  - The key is mounted into the API pods `optional: true`, so P2 can deploy before the key exists. `GITHUB_APP_ID` goes
    in `api.env`.
- **Minting** (`compose_api/environments/source_credentials.py`):
  - an app JWT, using the existing `pyjwt[crypto]`;
  - the installation, from `GET /repos/{o}/{r}/installation`;
  - `POST /app/installations/{id}/access_tokens`, scoped to the spec's restricted repositories with `contents: read`
    (1 h, the existing `httpx`). The token is never logged.
- **Mint before recording anything.** In `mash_up_for`, mint before `create_composed`. A mint failure is a 503 with
  nothing recorded, because a failed first version blocks that entry set with 409 until an admin intervenes.
- **Lock and uv-lock Jobs.**
  - Create the Job first (`K8sBuilds.create` currently drops the returned uid).
  - Then create a per-Job Secret with an ownerReference to it, without `blockOwnerDeletion`.
  - The Secret holds a gitconfig whose credential helper only answers `get` (an inline shell helper reading the mounted
    file, so git never tries to write to the read-only mount). The Jobs get `GIT_CONFIG_GLOBAL` pointing at it.
- **Build Job.**
  - An unprivileged init container clones each restricted repository at its locked commit into an emptyDir.
  - The privileged `apptainer build` sees only that clone, through a file-URL `insteadOf` gitconfig bound into the
    build.
  - So the token never enters the privileged pod that runs third-party build code, and can't expire during a build of
    up to 7200 s.
  - If that gitconfig can't reach `%post` without editing the definition (P0 probe), the edit keys on the spec's
    recorded roles, so only restricted hashes move.
- **RBAC:** the `compose-api-builds` Role gains `secrets: create, get, delete`.
- **Accepted and documented:** lock Jobs run package metadata and build code while the token is present. They are
  unprivileged, and the token is read-only, limited to those repositories and lasts at most 1 h.

## Work, in order

Each compose-api PR bundles the fix, its tests and the version bump, then tag → deploy, one release at a time.

**P0. Outreach and probes (no code).**
- **Nov (auth):**
  - roles `v2ecoli` and a probe role;
  - whether the "BioSim Roles" Action emits every assigned role;
  - **granting a role to someone before their account exists**: likely an allow-list keyed on *verified* email that
    assigns the role and adds it to that first token (`email_verified` is required);
  - each role adds bytes to the CLI session, and Windows' keyring item limit is 2560 B;
  - who assigns members later.

  **Member email addresses go to the Auth0 admins only**: never into this repository (public, archived to Zenodo),
  its issues or this plan. compose-api sees only the role name.
- **Jim (design):** an issue covering A–C, reviewed before P1 merges.
- **Eran:** the P4 list, agreed before any v2ecoli PR.
- **Probe, HPC permissions:**
  - `ls -ld` on each directory level down to `images/` and to an experiment directory;
  - the owners and modes of a SIF and a run's outputs;
  - `getent group` for the API and SLURM users.

  Then a decision to accept or fix (with Jim, if every run's mode changes).
- **Probe, git and apptainer:** in a single docker run with apptainer 1.3.6, check that the get-only helper and
  `GIT_CONFIG_GLOBAL` work under `pixi exec --spec git -- pixi lock`, that `--bind` on build works, and whether a bound
  gitconfig reaches `%post`.
- **Probe, v2ecoli lock:** run `docs/registry-onboarding.md` "Check that it locks" with a local credential, to replace
  the predicted blockers with pixi's actual errors.

**P1. compose-api: restricted entries, gates and the disk fix** (A, B).
- Tests:
  - a route-table-driven test covering every route in B: anonymous, plain `user` and other-role callers get 404 or
    filtered results, and holders see everything; a new route without a gate fails the table test;
  - the submission refusal is identical for a restricted class and an unregistered one, on the inferred and named
    paths;
  - covering never widens;
  - a restricted compliance run is unreadable to others, admin included;
  - alembic idempotency (`tests/common/test_migrations.py`) and the CI rules.
- Release.

**P2. compose-api: fetching private source** (C).
- Tests:
  - Jobs mount the secret only for restricted specs;
  - a sentinel token appears in none of pixi.toml, the lock, the definition or the Job env;
  - the token request lists exactly the spec's repositories;
  - a mint failure records nothing.
- Release. The App is created and its key sealed.

**P3. Prove it live on the probe repository** (`vivarium-collective/compose-private-probe`, private: one Step and one
case, shaped like viva-basic-processes).
- A manifest PR with `access_role`, then a release.
- Pre-flight: mint one token from an API pod.
- On production, as a holder: the mash-up locks, builds and passes compliance, and the results download.
- Negative sweep: every route in B as anonymous, as `user` and as `admin` without the role; `ghs_` absent from the
  lock, export, failure text, build log and SIF; file modes on the SIF and the run directory.
- A runbook for a failed first version: `compose-api environments create mash-…`.

**P4. v2ecoli readiness** (v2ecoli PRs, reviewed by Eran), driven by P0's real lock errors. Expected:
- Python `>=3.12,<3.13`, and resolve vEcoli's `==3.12.9`.
- Pin the sources to commits that work with the core's 1.9.1 and 1.8.1. If process-bigraph's newer scheduling is
  needed, a core bump is a separate decision.
- Ship the ParCa blob and the cache builder in the package.
- A short single-cell document with full addresses, which becomes the case. It must fit 2 CPU / 8 GB / 30 min
  (`job_script.py`).
- `conda:` compilers.
- torch/CUDA and vEcoli `[dev]` move out of the base dependencies.
- Keep the `method` type and dill-config imports out of the entry's `types`.
- Check `Metabolism` against `step-outputs-replace`.

**P5. Onboard and use v2ecoli.**
- The manifest entry (`access_role: v2ecoli`, roots `v2ecoli` and `pbg_v2ecoli`), its case, a release.
- As a holder, `compose-api run` → build → compliance → `status` → `results`.
- Then the workbench with `COMPOSE_API_TOKEN` and `serve --backend-base-url https://compose.cam.uchc.edu`.
  `resolve_environment` finds the entry only when signed in; no workbench change is expected (verify).
  `COMPOSE_API_TOKEN` is never renewed, so lasting use needs the open workbench item: use the CLI's stored session.

**P6. Docs.**
- `docs/registry-onboarding.md`: a "Private repositories" section.
- `docs/authentication.md`: fix its stale lines on roles and admin; add restricted entries and the role gate.
- `CLAUDE.md`: Authorization.

## Verification

- Per PR: `uv run python -m pytest tests/registry tests/api tests/environments tests/common -q` (Docker), `make
  check`, `make check-clients`, and an adversarial review.
- Mocked tests prove only shape: the spec, the Job manifest and the absence of the sentinel.
- **The live runs are the evidence that counts.** P3's end-to-end run and negative sweep on production gate P5. P5's
  CLI and workbench runs close the task.
