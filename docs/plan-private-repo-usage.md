# Private workspace repositories on compose-api (first case: vivarium-collective/v2ecoli)

**Status (2026-11-20): approved; P0 in progress.** A private viva workspace repository is onboarded (a registry entry
and an environment) and used (run, status, results) on compose-api, with v2ecoli as the first case of a general
mechanism. Checked against `main` at `53db5d9` (#547 merged). One PR per step, each merged with a merge commit;
deploying is a release, one at a time, as usual.

| Phase | What | State |
|---|---|---|
| P0 | Outreach (Auth0, design review, v2ecoli) and three probes; no code | in progress ("P0 results") |
| P1 | compose-api: restricted entries, gates and the disk fix (A, B) | gates built locally, unpushed; disk fix after 3(a) |
| P2 | compose-api: fetching private source (C) | built locally, unpushed; local probes pass ("P2 results") |
| P3 | ~~Prove it live on a tiny private probe repository~~ | dropped: the live trial is on v2ecoli, in P5 |
| P4 | v2ecoli readiness (v2ecoli PRs) | list from the real lock (below) |
| P5 | Onboard v2ecoli, prove it live, and use it | — |
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
- **v2ecoli does not lock as it is** (separate from credentials; measured in P0): its `[tool.uv.sources]` send
  process-bigraph to `main` (1.11.0), which clashes with the core's 1.9.1. With the two core pins taken from the index,
  it locks. It also cannot run yet:
  - the ParCa blob and cache builder are not in the wheel;
  - no saved document uses full `local:module.Class` addresses;
  - its Cython, and vEcoli's source distribution, need a compiler at build time.

  Eran (eagmon) owns the repository.

## Decisions (2026-11-19)

1. **The access list is an Auth0 role per private repository.** The entry names the role, and the members are the
   tenant users who hold it. There is **no admin bypass**: an operator who needs access is given the role.
   - Auth questions go to Nov. compose-api design review goes to Jim.
   - The v2ecoli members are people who have not signed up yet (P0).
2. **Entry metadata may be public**: repository URL, commit, module roots, and a compliance case that is a document
   only. Code, images, locks, interfaces, failure text and runs stay private: hidden by the API and unreadable on disk.
3. **v2ecoli is composed from git**, not a prebuilt image. There is no probe repository (2026-11-20): P2 is proven
   locally on a stand-in, and live on v2ecoli itself once it is ready (P4), in P5.
4. **We open and merge the v2ecoli PRs ourselves**, working actively with Eran but not gated by him.

## Design

### A. Restricted entries

- A manifest entry gains an optional `access_role: <name>` (`registry/manifest.py`; not empty, not `user`).
- `create_composed` (`environments/service.py`) records the version's roles in its spec (`spec["access_roles"]`).
  Everything about a version and its runs then uses those recorded roles, so a later manifest edit can't narrow them.
  An environment needs the roles all its versions recorded as well (`access.recorded_roles`), so removing an entry
  or renaming its role hides nothing less; built in P1.
  Changing an entry's role means a new version. Runs from before a role was added stay as they were (documented).
- **Removing a member is not immediate** (Nov, P0). compose-api reads roles from the access token, which stays valid
  for up to 24 h after the role is removed, so a removed member keeps access until it expires. That is a delay in
  revoking a member, not access for anyone who never held the role, so compose-api needs nothing for it (documented
  in `docs/authentication.md`). The member must also leave the allow-list, or the Action gives the role back at their
  next sign-in.
- **CI rules** (`tests/registry/`). A restricted entry:
  - is never in a shared or `core` environment, `solvers.yaml`, or a suite;
  - is never in an unrestricted entry's `requires`;
  - has no `module_roots` overlapping another entry's, and no `alternative_to`;
  - has a compliance case that is a document only;

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
  - No `Vary: Authorization` and no web UI change: a hidden name is a 404 before any ETag comparison, gated responses
    carry no freshness, and signing in or out reloads the page. A session that expires in place keeps showing what that
    same person saw until they sign in again.
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

- **compose-api's own GitHub App** (2026-11-20): private, owned by `vivarium-collective`, with Contents read-only and
  no webhook, installed on v2ecoli only. Alex, an owner of the organization, created it:
  [`compose-api-private-source`](https://github.com/apps/compose-api-private-source), App ID 5850349.
  - A private App can be installed only on the account that owns it, so a private repository in another organization
    later needs this App made public, or a second App.
  - Not an existing App: any App's key mints tokens for every repository it is installed on, so sharing one widens
    what its key reaches.
  - Its key is the SealedSecret `github-app` in `kustomize/overlays/compose-api-rke`, made by a new
    `kustomize/scripts/sealed_secret_github_app.sh` copied from `sealed_secret_ghcr.sh`. The key is generated when the
    release PR that seals it is ready, and goes straight from GitHub into that script.
  - The key is mounted into the API pods `optional: true`, so P2 can deploy before the key exists. `GITHUB_APP_ID` goes
    in `kustomize/config/compose-api-rke/api.env`, in P2's release PR (deploy-guard allows deploy config there only).
    Without both, a private repository's version is a 503 and no version is recorded.
- **Minting** (`compose_api/environments/source_credentials.py`):
  - an app JWT, using the existing `pyjwt[crypto]`;
  - the installation, from `GET /repos/{o}/{r}/installation`;
  - `POST /app/installations/{id}/access_tokens`, scoped to the spec's restricted repositories with `contents: read`
    (1 h, the existing `httpx`). The token is never logged.
  - One organization per version, since a token comes from one installation.
  - A token is reused for the same repositories while it has more than 40 minutes left (a lock Job's 30, and a
    margin), so a version's creation and lock share one. A build asks for one with 55 minutes left, usually a new
    one, because its clone runs only when its pod starts.
- **Mint before recording anything.** `create_composed` mints before it records the version, for a mash-up and the
  create-version route alike. A mint failure is a 503 with no version recorded, because a failed first version blocks
  that entry set with 409 until an admin intervenes.
- **Lock and uv-lock Jobs.**
  - Create the Job first (`K8sBuilds.create` returns it, with its uid).
  - Then create a per-Job Secret with an ownerReference to it, without `blockOwnerDeletion`. If the Secret cannot be
    created, the Job is deleted at once rather than left waiting for it until its deadline.
  - The Secret holds a gitconfig whose credential helper only answers `get`:
    `!f() { if [ "$1" = get ]; then cat /run/compose-git/credentials; fi; }; f`. It is an inline shell helper reading
    the mounted file, so git never tries to write to the read-only mount. The Jobs get `GIT_CONFIG_GLOBAL` pointing at
    it.
  - Measured in P0: against the private repository, `git ls-remote` and a fetch of the pinned commit worked and wrote
    nothing to the mount. pixi's lock honours `GIT_CONFIG_GLOBAL`. The lock records the `https` URL, never a rewrite.
- **Build Job.**
  - An unprivileged init container, `clone`, clones each restricted repository at its locked commit (`--depth 1`) into
    the work emptyDir. It runs in the pixi image as the service user, its git brought by `pixi exec --spec git` as a
    lock Job's is, and is the only container that mounts the Secret.
  - The privileged `apptainer build` sees only that clone, through a file-URL `insteadOf`.
    - The emptyDir's `git` directory, holding the clones and that gitconfig, is bound onto `/mnt`, and the build
      process gets `APPTAINERENV_GIT_CONFIG_GLOBAL=/mnt/gitconfig`.
    - The gitconfig also sets `safe.directory` (the clone has another owner) and `uploadpack.allowAnySHA1InWant`, as
      the P0 lock probe did.
    - Each private URL is mapped with and without `.git`. git rewrites a URL by its longest matching `insteadOf`, so
      any other locked git URL that a private one is a prefix of (`…/v2ecoli-extras`) is mapped to itself.
    - The clone is shallow, so when uv fetches the commit from it (`+<sha>:refs/commit/<sha>`), git keeps no ref, but
      the commit arrives, and uv uses only the commit. A full clone would fetch v2ecoli's whole 1.2 GB history for
      every build. uv's behaviour is fixed by the pinned pixi image, and the P2 probe built through it.
  - Measured in P0 with apptainer 1.3.6 on the production pixi base:
    - `build --bind` needs a destination that already exists in the base. `/mnt` does, so a file bind onto
      `/etc/gitconfig` fails.
    - The build's own environment does not reach `%post`, but the `APPTAINERENV_` prefix does.
    - Neither the bind nor the variable is kept in the SIF.
    - So the definition, and every hash, stays as it is.
  - So the token never enters the privileged container that runs third-party build code, and can't expire during a
    build of up to 7200 s. The Secret is still a volume of the build's pod: a privileged container that escaped to its
    node could read it there, as it could any Secret on that node. It would gain only read access to repositories whose
    code the build already holds.
  - The clone must start within the token's hour. A pod that waits longer for a node fails to clone, and its build
    with it.
  - The build asks for its token when it starts. If GitHub refuses, nothing is created, and the version is failed with
    that reason, which a mash-up's 409 repeats.
- **RBAC:** the `compose-api-builds` Role gains `secrets: create` only. The ownerReference has Kubernetes delete each
  Secret with its Job, so the API never reads or deletes one.
- **Release:** P2 changes `kustomize/base`, so deploy-guard passes it only as a release PR, which also carries
  `GITHUB_APP_ID` and the sealed key.
- **Accepted and documented:** lock Jobs run package metadata and build code while the token is present. They are
  unprivileged, and the token is read-only, limited to those repositories and lasts at most 1 h.

## Work, in order

Each compose-api PR bundles the fix, its tests and the version bump, then tag → deploy, one release at a time.

**P0. Outreach and probes (no code).**
- **Nov (auth):**
  - a role per repository;
  - whether the "BioSim Roles" Action emits every assigned role;
  - **granting a role to someone before their account exists**: likely an allow-list keyed on *verified* email that
    assigns the role and adds it to that first token (`email_verified` is required);
  - each role adds bytes to the CLI session, and Windows' keyring item limit is 2560 B;
  - who assigns members later.

  **Member email addresses go to the Auth0 admins only**: never into this repository (public, archived to Zenodo),
  its issues or this plan. compose-api sees only the role name.
- **Jim (design):** issue #552 covers A–C, and it is reviewed before P1 merges.
- **Eran:** the P4 list, worked through with him (decision 4).
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

**P0 results (2026-11-19).**
- **Auth0 (Nov):** answered.
  - v2ecoli's role is `repo-v2ecoli` (a `repo-` prefix for repository roles), made through auth0-pulumi.
  - Every role a user holds is in the roles claim, in BioSim Platform tokens as well as compose-api's.
  - People without an account get theirs from an allow-list in the BioSim Roles Action, applied only when
    `email_verified`, the list kept as Pulumi secrets. Google sign-in is recommended for members until the tenant has
    a production email provider.
  - Removing a member takes effect when their token expires (section A).
  - Repository owners decide who is a member; changes are auth0-pulumi PRs.
  - One role adds about 25 bytes to a CLI session, so Windows' 2560 B leaves room for about 30 more.
- **git and apptainer:** done, with results under C. No change to the image definition is needed.
- **The v2ecoli lock:** done. This was `pixi_toml()` from `main` at 36b328c, for v2ecoli at e9250af, in the pinned
  pixi image. v2ecoli was fetched from a local clone through a file-URL `insteadOf`, so no credential was used.
  - As it is, the lock fails on one thing only: process-bigraph from `main` (1.11.0) against the core's `==1.9.1`.
  - With `dependency-overrides` for the two core pins, it locks. That is the mechanism `INDEX_ONLY` already uses.
    - Python resolves to 3.12.16, so the `==3.12.12` and `==3.12.9` pins do not block.
    - 333 PyPI and 22 conda packages, including torch 2.15 with 15 NVIDIA wheels.
    - vEcoli comes as a source distribution, so the build compiles it.
  - Eight git sources still follow `main`, which the onboarding check refuses: Viva-munk, investigation-contracts,
    spatio-flux, viva-bioreactordesign, viva-copasi, viva-ketchup, viva-torch, viva-workspace.
  - Whether composed locks should always override the core pins is question 4 in #552.
- **HPC permissions:** waits on a run from a login node, by an ordinary (non-service) account. Running it as such an
  account is itself the test.

**P2 results (2026-11-20, local).** The Jobs P2 generates, run in Docker as the cluster runs them (amd64; the service
user; privileged Apptainer 1.3.6), with scratch and work as volumes:
- **A stand-in private repository**, behind its GitHub URL, was locked, cloned and built:
  - the lock records the `https` URL at the commit, with no file URL;
  - the package imports from the image;
  - `/mnt` is empty and `GIT_CONFIG_GLOBAL` unset in the image;
  - a sentinel token is in neither the image nor the work volume;
  - the image's definition is the version's, byte for byte.
- **v2ecoli itself**, from github.com, was fetched by pixi's lock through the credential helper. The workspace set
  `no-build`, so no package code ran beside the local credential used.
  - With a wrong token, the fetch fails. With a good one, it gets past the fetch, v2ecoli's commit is in the cache,
    and the lock stops at `vecoli[dev]`, which has no wheel.
  - Neither token is in any log or the cache.

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
- Release, with the App's key sealed in it (section C).

**P3. Dropped** (2026-11-20). There is no probe repository; its live trial is v2ecoli's, in P5.

**P4. v2ecoli readiness** (v2ecoli PRs that we open and merge, working with Eran; decision 4), from P0's real lock:
- **process-bigraph and bigraph-schema** take releases, not `main`, unless compose-api overrides the core pins (#552,
  question 4). v2ecoli's composites do not run on process-bigraph 1.9.1 (ecoli_baseline has a step cycle across
  priorities, which 1.9.1 refuses), so compose-api's core moves to process-bigraph 1.11.1 with bigraph-schema 1.8.3
  (#563). That satisfies what v2ecoli requires (process-bigraph >=1.11.0, bigraph-schema >=1.8.3) and matches its own
  lock, where a uv override holds bigraph-schema at 1.8.3.
- **The eight `main` sources** are pinned to commits or releases.
- **Size:** torch/CUDA (through viva-torch) and vEcoli's `[dev]` tooling move out of the base dependencies, if a
  single-cell run doesn't need them.
- **Python:** the pin is relaxed to `>=3.12,<3.13`, which the lock already shows works. Check that the ParCa pickle
  loads on 3.12.16.
- **Runtime data:** the ParCa blob and the cache builder ship in the package.
- **A document:** a short single-cell one with full addresses, which becomes the case. It must fit 2 CPU / 8 GB / 30 min
  (`job_script.py`).
- **Compilers:** `conda:` compilers on the entry, which is compose-api's side.
- **Address-check gaps:** keep the `method` type and dill-config imports out of the entry's `types`.
- **step-outputs-replace:** check `Metabolism` against it.

**P5. Onboard v2ecoli, prove it live, and use it.**
- The manifest entry (`access_role: repo-v2ecoli`, roots `v2ecoli` and `pbg_v2ecoli`), its case, a release.
- Pre-flight: mint one token from an API pod.
- On production, as a holder: the mash-up locks, builds and passes compliance, and the results download; then
  `compose-api run` → `status` → `results`.
- Negative sweep: every route in B as anonymous, as `user` and as `admin` without the role; `ghs_` absent from the
  lock, export, failure text, build log and SIF; file modes on the SIF and the run directory.
- A runbook for a failed first version: `compose-api environments create mash-…`.
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
- **The live runs are the evidence that counts.** P5's end-to-end run and negative sweep on production come before
  anyone else uses v2ecoli there; its CLI and workbench runs close the task.
