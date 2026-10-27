# Web UI: sign-in switched on, and the administrative tasks brought into it

**Status (2026-10-27): done (CSP enforced #436; 5c in 0.7.59; 6 in 0.7.60; step 5's suite page in 0.7.61). Left:
Jim's signed-in check of steps 5–6 in production.** It continues [plan-webapp-login](plan-webapp-login.md), whose work is done apart
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
   - **The CSP has reported nothing.** Loki for 2026-10-11 to 2026-10-25 shows no `CSP violation report` lines and
     no `POST /webapp/csp-report` requests, while `/ui` served 80 to 580 requests a day. What it has not seen yet is
     the sign-in flow itself: the redirect to Auth0, the token calls to it, and profile pictures.
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

## Decisions (Jim, 2026-10-25: A1–A5 confirmed)

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
   - *As built (2026-10-26):*
     - `capabilities` names `environments:admin`, `suites:curate` (known problems, added since the decisions) and
       `simulations:read-all`, each computed by its enforcing check (`authorization.CAPABILITIES`). The field has a
       default, so a client talking to an older release reads none. `compose-api auth status --verify` prints them.
     - The diff compares what the two images installed (`installed`, PEP 503 names, as the webapp's version view
       does), not their locks: `lock.changes` and `PackageChange` left with composition step 8d, and the read-back
       exists for every version, registry_env@1 and prebuilt images included. A version with nothing read back yet
       is a 409. CLI: `environments version NAME N --against M`.
     - The guard holds a suite while a run is still `submitting`, or while a run under two days old
       (`suite_runs.IN_FLIGHT_FOR`) has members not finished. Past that it is stalled, not running, so one stuck
       simulation cannot block the suite for good. Two requests at the same instant can still both start.
4. **Enforce the CSP** (`WEBAPP_CSP_ENFORCE=true` in `api.env`, deploys on merge).
   - Two weeks of ordinary use have already produced no reports (findings, 1). Only the sign-in flow is unmeasured,
     so enforcing can follow step 1 by a few days, not weeks: long enough for several people to sign in, renew a
     session and sign out.
   - Before enforcing, read the logged reports in Loki (`CSP violation report`) and allow what is legitimately
     needed.
   - Then repeat the smoke test, and open each viewer (Plotly, the composite viewer, zarr).
   - *As built (2026-10-26):* Loki for the 7 days to 2026-10-27 02:00Z shows no `CSP violation report` line, across
     22 `/auth/me` calls from sign-ins on 10-25 and 10-26. A test report posted by hand was logged, so the pipeline
     works and the silence is real. The build has no `eval` or `new Function`; its one `importScripts` is MapLibre's
     map-trace worker (Plotly), which `worker-src 'self' blob:` allows. The policy is unchanged;
     `WEBAPP_CSP_ENFORCE=true` is set in `api.env`.
5. **Read-only version pages (step 5b of plan-environment-versions).**
   - *2026-10-26:* the Versions section and the version view are built: packages with a diff against another
     ready version, entries with their compliance level and cases, classes, and the pixi/uv files. The suite page's
     version picker and the simulation and comparison pages are still to do.
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
   - *As built, the suite page (2026-10-27):* "Run the suite" is disabled while signed out (when sign-in is offered)
     and opens a confirmation (`ConfirmDialog`) with the number of simulations it submits and a version picker per
     environment its solvers use (`utils/suites.ts`: `suiteEnvironments`, `versionChoices`, default first, then ready
     versions newest first); the request names each (`versionParameters`), and a 409 shows in the dialog. The run
     picker and a line under it show each run's versions, linked to their pages. The environment page's "Read back"
     is renamed "Re-read contents", with a tooltip on each action.
   - **The simulation and comparison pages:** show the `environment_version` each run used. Simulations already carry
     it as a label.
   - Webapp only (`useRegistry.ts` gains the version calls), and it ships with a release.
   - **5c. Every run links to where it ran, and every environment to its runs** (Jim, 2026-10-26).
     - *The hole.* Every run records its simulator (`simulation.simulator_id`: a container definition and its hash),
       but only runs since environment versions also record a version. In production, 5,935 of 8,636 runs (69%) ran
       on 18 simulators that are no environment's version: they ran before versions existed (image 132 alone has 3,461
       runs, from 2026-05). Nothing lists those simulators or shows their definitions, apart from the deprecated
       `GET /core/simulator/list`.
     - *Not backfilled as versions.* registry_env@1 is already simulator 286, so older simulators would need numbers
       below 1, and versions made the old way stay as they are (composition D8.2). A simulator is addressable on its
       own instead, and a version links to its simulator.
     - **API (one PR):**
       - `GET /registry/simulators` (`list-simulators`): every simulator that is a version or that a readable run
         used, with the versions it is (`environment`, `number`), how many readable runs used it, and their first and
         last dates. `GET /registry/simulators/{id}` (`get-simulator`) adds its definition.
       - `GET /simulations` gains `simulator_id`, `environment` (any version of it) and `environment_version`
         (`name@n`). The last two match the stored version id, not the label, which is a name snapshot and which
         a third of the versioned runs lack.
       - Each simulation summary gains `environment_version` (`environment`, `number`), from the stored id with the
         environment's current name.
       - A migration backfills `simulation.environment_version_id` for runs whose simulator is exactly one version's:
         a run on simulator 286 before registry_env@1 was recorded ran in that image.
       - CLI: `simulators history`, `simulators show`, and `simulations list --simulator-id/--environment/
         --environment-version`.
       - *As built (2026-10-26):* the routes, filters and summary field as above (`VersionRef`, `SimulatorSummary`,
         `SimulatorDetail`; `EnvironmentsDatabaseService.version_links`, `SimulatorDatabaseService.simulator_uses`).
         Run counts and dates count only runs the caller may read (`readable_clause`). An unknown environment or
         version in a filter is a 400, like an unknown label key. The backfill is alembic `a7d4c2e9b513`; the
         CLI's simulation table gains a `version` column.
     - **Webapp (one PR):** the simulation and comparison pages link each run to its version, or to its simulator's
       page when it has none. The simulator page shows its definition, its versions and "N runs". The environment
       page's versions and each version view link "N runs" to the filtered simulation list. The environments page
       gains a collapsed "Earlier simulators (before versions)" section.
       - *As built (2026-10-26):* `RanIn` (a run's version, or its simulator) on the simulation page, the list's
         "Ran in" column and each comparison member; `utils/environments.ts` `ranInLink`/`runsLink`; the new page
         `/simulators/{id}` (definition, downloadable); "Runs" links on the environment page (all versions, and per
         version once used) and the version view, whose simulator id links to its page; the list's filters from the
         query, cleared with one chip.
6. **Admin actions in the webapp.** Shown only with `environments:admin`; ship only after step 4. Each one gets a
   confirmation dialog (A3):
   - **Refresh a shared environment:** preview (date, default today; the lock diff and package count), then confirm to
     create. The new version's state is polled until ready or failed, and the build's failure reason is shown.
     *Since composition 8d there is no preview:* a new version is inert until it is made the default, so the dialog
     confirms the date (and a note), and the package diff is shown where it takes effect, in the "Set the default"
     dialog (against the current default, `?against=`).
   - **Register a prebuilt image:** the image reference must be by digest (the API refuses others), with a note. Its
     inspection runs, and its state is followed.
   - **Set the default:** only for a ready version. The dialog says which runs this affects: requests that name no
     version, not suite runs.
   - **Retire:** refused for the default. The dialog says runs already recorded keep their version.
   - **Re-read a prebuilt version's contents (inspect).**
   - Not offered: custom library lists (A3).
   - Vitest tests cover the capability gating and each dialog, against mocked API responses.
   - *As built (2026-10-27):* `utils/admin.ts` decides what to offer (`canAdminister`, `versionActions` by state and
     default, `isDigestReference`) and what each dialog says (`confirmation`, `creationConfirmation`), tested in
     `test/admin.test.ts`; the webapp has no component-test library, so the logic is kept pure. `EnvironmentAdmin`
     (the environment page's Versions section) holds the dialogs (`ConfirmDialog`) and follows a new version every 5 s
     until it settles; each version row gets its actions. The account menu links "You can administer environments".
     Retire is offered only for a ready or failed version: a version still resolving or building is finished by its
     build, which would overwrite the state. Checked in headless Chromium against production with the admin routes
     mocked: no controls when anonymous; each dialog's text, the diff, and the requests' bodies.
7. **Documentation.**
   - `docs/webapp.md`: signing in, the version pages, and the admin actions with who sees them.
   - `docs/authentication.md`: `/ui` as a human caller, and the capabilities.
   - Close plan-webapp-login (W5) and step 5b of plan-environment-versions.
   - *As built (2026-10-27):* `docs/webapp.md` gains the version and simulator pages in its table, the capability
     line in "Sign-in", and an "Administration" section (who sees it, each action, the dialogs, the CLI
     equivalents). `docs/authentication.md` gains the web UI under "Human callers", the three role settings under
     "Roles" (it said at most one was checked), and a "Capabilities" section. plan-webapp-login is closed (W2 live, W5
     done). plan-environment-versions 5b points here: its pages are built except the suite page's, step 5's
     remainder.

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
