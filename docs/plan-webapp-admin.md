# Web UI: sign-in switched on, and the administrative tasks brought into it

**Status (2026-10-25): proposed.** It continues [plan-webapp-login](plan-webapp-login.md), whose work is done apart
from switching it on (W2, #359), and step 5b of [plan-environment-versions](plan-environment-versions.md), the
webapp's environment version pages. One PR per step, each merged with a merge commit. Steps that change
`kustomize/` deploy on merge; the others reach production with a release.

## Findings (2026-10-25)

1. **Sign-in is built but switched off.**
   - W1 is done: the Auth0 SPAs were deployed 2026-10-23 (UCHHPC/auth0-pulumi#5).
   - W3 and W4 are done and have shipped in every release since 0.7.30:
     - the return target, the token allowlist, sign-up, `/auth/me` after sign-in, and expired sessions
       (`composables/useAuth.ts`, `components/AuthMenu.vue`);
     - the `/ui` security headers, with the Content-Security-Policy in report-only mode and reports logged by
       `POST /webapp/csp-report` (`api/webapp.py`).
   - The only thing missing is the client id (#359, W2). Until it is published, `/webapp/config` gives the app no
     client id and the "Sign in" button never renders.
   - Nobody has measured the CSP: reports arrive only when people use `/ui`, and few do while sign-in is off.
2. **Administration happens only from the command line.**
   - The admin actions are preview, create, set the default, retire, and inspect an environment version. They exist
     only as `compose-api environments …` commands.
   - They answer 403 for everyone, because `ENVIRONMENT_ADMIN_ROLE` is not set in `api.env`.
   - The environment page (`pages/environments/[name].vue`) shows the image's build state, the committed manifest's
     packages and the classes. It knows nothing about versions.
3. **The webapp cannot tell what the caller may do.**
   - `/auth/me` returns the token's roles, but which role grants what is server configuration (`admin_role`,
     `environment_admin_role`).
   - A webapp that matched role names would duplicate that configuration, and would drift from it.
4. **Starting a suite run is open to anyone, anonymous included.**
   - `POST /suites/{name}/run` starts a SLURM job for every source and solver. For biomodels-curated-300 that is about
     1,200 jobs.
   - The suite page offers "Run the suite" to every visitor and always sends `environment_version=default`.
   - Nothing stops a second run of the same suite while one is still going.
   - The monthly `sedml-suites.yml` workflow calls the route anonymously, so it has no identity a role could be checked
     against.
   - `POST /suites/{name}/runs/{n}/verify` is open too, but it is cheap and idempotent.
5. **Nothing compares two versions' packages.**
   - The preview diffs a proposed lock against the default.
   - `GET …/versions/{n}` returns one version's lock and installed packages, with no way to compare it to another.

## Decisions (proposed; to confirm)

- **A1. The API says what the caller may do; the webapp only displays it.**
  - `GET /auth/me` gains `capabilities`, a list of names such as `environments:admin` and `simulations:read-all`.
  - They are computed by the same functions in `authorization.py` that enforce them (`is_environment_admin`,
    `_is_admin`), so the two cannot disagree.
  - The webapp shows admin controls only when the capability is present. The server still checks every request, so a
    hidden button is never the protection.
  - The change is additive to the response, so pbest and the 0.2.x client are unaffected. The CLI's `auth whoami`
    prints it.
- **A2. Admin actions sit next to what they act on**, not in a separate admin area.
  - The environment page gains a Versions section, and the admin actions appear in it.
  - When signed in with a capability, the account menu shows a "You can administer environments" line linking there.
  - A separate `/admin` area is worth adding only once there is more than one kind of thing to administer.
- **A3. The admin token stays in the PKCE SPA (D1 of plan-webapp-login holds), on three conditions.**
  - D1 said to revisit a backend-for-frontend if the UI came to hold higher-value permissions, and environment
    administration is one. Its worst case is limited, though: a refresh brings in new code only through reviewed
    registry entries, and defaults and retirement are reversible.
  - The conditions:
    1. **The CSP is enforced before any admin write action ships in the webapp** (step 4 before step 6). Read-only
       version pages can ship earlier.
    2. **Custom library lists stay CLI-only.** `origin=custom` runs unreviewed code as root on the privileged
       builder, so it is the one action whose blast radius would argue for a backend-for-frontend.
    3. **Every admin action is confirmed in a dialog** that names the environment, the version and the effect. A
       create shows the lock diff before it is confirmed.
- **A4. Suite runs: one in flight per suite now; a role later.**
  - Now: `POST /suites/{name}/run` answers 409 while a run of that suite is still submitting or running, with a link
    to that run.
  - The webapp's run button needs sign-in, which is a nudge, not a guard. It also gets a version picker.
  - Later: gate the route on an operator capability, once the monthly workflow has a machine identity. That means an
    Auth0 machine-to-machine application with a role (Novrus, auth0-pulumi). A credentials-exchange action, not the
    post-login one, would stamp its roles.
  - Accepting a baseline stays a PR to `suite.yaml`, reviewed and in git.
- **A5. The role.**
  - `ENVIRONMENT_ADMIN_ROLE=admin`, the tenant's existing `admin` role, which Jim assigns himself in Auth0.
  - The role is tenant-wide; nothing else in compose-api reads it, because `ADMIN_ROLE` (read every private
    simulation) stays unset.
  - If environment administration should ever go to someone who is not a tenant admin, ask Novrus for a narrower role
    such as `compose-environment-admin` and change the one setting.

## Steps

1. **Switch sign-in on (W2, #359).**
   - Bring the PR up to date with `main` and tick its two gates:
     - W3 and W4 are enough;
     - the CSP stays report-only for now (step 4).
   - Merge it. It deploys, and sign-in appears at the next pod restart.
   - Run plan-webapp-login's smoke test at `https://compose.cam.uchc.edu/ui/`: sign up and sign in with email and with
     Google, land back on the page you started from, see your roles, reload, sign out, and see an expired session.
2. **Set the admin role** (`kustomize/config/compose-api-rke/api.env`, deploys on merge).
   - Done after Jim has the tenant `admin` role.
   - Verify with `compose-api environments preview registry_env`, which should now answer 200 instead of 403.
   - This also unblocks registry_env@2 (libvcell 0.0.24) from the CLI, independently of the rest of this plan.
3. **API: capabilities, the version diff, and one suite run at a time.**
   - `CurrentPrincipalResponse.capabilities` (A1), built in `authorization.py`.
   - `GET /registry/environments/{name}/versions/{n}?against=<m>` adds `changes: list[PackageChange]`, made by the same
     `lock.changes` the preview uses, so the CLI can diff too (`environments version … --against`).
   - The suite run guard (A4), with a test.
   - Regenerate the spec and the client, and add the CLI options. This needs a release.
4. **Enforce the CSP** (`WEBAPP_CSP_ENFORCE=true` in `api.env`, deploys on merge).
   - Wait about two weeks after step 1, with people signing in.
   - Before enforcing, read the logged reports in Loki (`CSP violation report`) and allow what Nuxt, Plotly and the
     viewers legitimately need: script hashes, or `'unsafe-eval'` if a viewer needs it.
   - Then repeat the smoke test, and open each viewer (Plotly, the composite viewer, zarr).
5. **Read-only version pages (step 5b of plan-environment-versions).**
   - **The environment page's Versions section:** each version's number, state, the default badge, origin, the
     resolution date or image digest, who created it, and its note.
   - **A version view (`/environments/{name}/versions/{n}`):** installed packages, the lock (downloadable), a diff
     against another version (picker, default: the default version), and its interfaces. The class list reuses the
     existing manifest rendering.
   - **The suite page:**
     - an environment version picker for "Run the suite": defaulting to each environment's default, listing ready
       versions;
     - each run's `environment_versions` shown beside it;
     - the button disabled while signed out (A4).
   - **The simulation and comparison pages:** show the `environment_version` each run used. Simulations already carry
     it as a label.
   - Webapp only (`useRegistry.ts` gains the version calls), and it ships with a release.
6. **Admin actions in the webapp.** Shown only with `environments:admin`; ship only after step 4. Each one gets a
   confirmation dialog (A3):
   - **Refresh a shared environment:** preview (date, default today; the lock diff and package count), then confirm to
     create. The new version's state is polled until ready or failed, and the build's failure reason is shown.
   - **Register a prebuilt image:** the image reference must be by digest (the API refuses others), with a note. Its
     inspection runs, and its state is followed.
   - **Set the default:** only for a ready version. The dialog says which runs this affects: requests that name no
     version, not suite runs.
   - **Retire:** refused for the default. The dialog says runs already recorded keep their version.
   - **Re-read a prebuilt version's contents (inspect).**
   - Not offered: custom library lists (A3).
   - Vitest tests cover the capability gating and each dialog, against mocked API responses.
7. **Documentation.**
   - `docs/webapp.md`: signing in, the version pages, and the admin actions with who sees them.
   - `docs/authentication.md`: `/ui` as a human caller, and the capabilities.
   - Close plan-webapp-login (W5) and step 5b of plan-environment-versions.

Steps 1 and 2 are configuration and can go today. Steps 3 and 5 can proceed in parallel. Step 6 waits for both 3
and 4.

## Verification

- Step 3: route tests.
  - `/auth/me` capabilities: none for a plain user, and `environments:admin` with the role configured. With the
    setting empty, nobody has it.
  - A diff between two versions' locks.
  - A second suite run answers 409 while the first is running, and starts once the first has finished.
- Steps 5 and 6: `make webapp-check` with the new vitest tests. By hand, with `make webapp-dev` against the production
  SPA:
  - as a signed-in non-admin: the version pages render, and no admin controls show;
  - as an admin: preview registry_env, cancel, then create @2 for real (the libvcell 0.0.24 refresh, if step 2
    has not already done it from the CLI), and follow it to ready;
  - run the Ciliberto suite on @2 from the suite page's picker;
  - set @2 as the default only after the 300-model comparison holds up.
- In production, after each deploying step: plan-webapp-login's smoke test, and no new CSP reports after step 4.

## Later (not in this plan)

- Owner at submission and a "My simulations" view (plan-observability step 5); then `ADMIN_ROLE` and private runs.
- Gate suite runs on an operator capability, with a machine identity for the monthly workflow (A4).
- Authorization as declarative policy (Oso, enforced through SQLAlchemy). The `capabilities` list would then come
  from the policy, not from hand-written checks. See the "Later" paragraph in plan-environment-versions.
- A backend-for-frontend, if the UI comes to offer custom library lists or anything else that runs unreviewed code
  (A3).
