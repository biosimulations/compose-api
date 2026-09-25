# Auth0 Cross-Repository Remaining Implementation Plan

**Generated:** 2026-09-25
**Repositories reviewed:** `/Users/novrusshehaj/Github/UCHC/compose-api`,
`/Users/novrusshehaj/Github/UCHC/auth0-pulumi`, and the dependent
`/Users/novrusshehaj/Github/UCHC/platform` call sites
**Purpose:** Define the smallest safe, evidence-backed implementation and validation sequence
for the Auth0 work that remains after the cross-repository audit.
**Current readiness:** **Not ready to push or deploy.** This document is a plan only; it does
not authorize live changes.

## 1. Executive summary

The Compose authentication verifier, optional-bearer contract, principal/roles handling, JWKS
failure behavior, deployment audience wiring, generated-client compatibility, and deterministic
tests are already implemented and were validated by the audit. The BioSim Roles Action source,
its `update:users`-only dedicated client grant, the production-only Compose user grant, and the
RKE source URL corrections are also present in the working trees and covered by offline tests.

Remaining blockers are policy and live-environment blockers, not a reason to reopen the completed
JWT hardening. The shared BioSim SPA has live localhost callback/logout entries while Pulumi
intentionally removes localhost as a security remediation; the Platform account deletion path
requires `delete:users`, while the live backend M2M grant lacks it and also contains broader
client/role administration privileges whose ownership and consumers have not been established.
Real browser signup/sign-in, callback exchange, refresh-token renewal, and first-login role
assignment have not been exercised.

Recommended order: decide the local-client policy without weakening the production client,
trace and reconcile the backend Management grant, implement and test only the approved source
changes, run offline gates and refreshed non-destructive previews, obtain explicit authorization
for live applies and user testing, apply the approved stacks in dependency order, then perform
the authorized smoke test and final diff/readiness review. The RKE live allowlist application and
frontend-to-Compose person-token flow remain intentionally skipped as described below.

## 2. Scope

### In scope

- Resolve the localhost callback/logout/web-origin conflict while preserving production security.
- Review every scope on the Platform backend’s Auth0 Management API M2M grant against actual
  consumers.
- Add `delete:users` or redesign the deletion capability only after the ownership decision is
  documented.
- Remove unneeded Management API scopes only after a consumer/owner inventory proves they are
  unused.
- Make corresponding, minimal changes in `auth0-pulumi`, `platform`, and `compose-api` where
  configuration or CORS/API compatibility requires them.
- Add/update offline tests for the selected policy and grant contract.
- Run Pulumi offline tests, non-destructive previews, repository quality gates, and final Git
  review.
- Conduct an explicitly authorized browser/user smoke test for signup/sign-in, callback,
  session renewal, and first-login role assignment.
- Verify account deletion only if the live test is separately approved.

### Explicitly out of scope / skipped

- **RKE Auth0 callback/logout origins are fixed in source but not applied live.** Do not add a
  separate implementation task for applying this item. It may be a dependency of the authorized
  final live verification, but it is intentionally skipped by this plan.
- **Frontend-to-Compose person-token end-to-end compatibility.** The frontend has no Compose API
  call site; do not invent one or add frontend-to-Compose work solely to close this audit
  limitation.
- Reopening the completed Compose JWT/JWKS hardening, changing public-route authorization,
  introducing local user persistence, changing operation IDs, changing the generated client by
  hand, or bundling unrelated cleanup.
- Creating/deleting Auth0 users, changing live grants, applying Pulumi, deploying workloads, or
  changing live tenant configuration during this planning task.

## 3. Repository evidence and current-state findings

| Concern | Repository | File / symbol | Current behavior | Planning implication |
|---|---|---|---|---|
| Inbound Compose authentication | compose-api | `compose_api/authentication.py`: `Auth0Verifier`, `JwksCache`, `_principal_from_claims` | Optional bearer authentication accepts verified Auth0 access tokens, derives `user` plus the namespaced roles claim, and fails closed on malformed/rotated JWKS paths. | Treat as completed baseline; only change if a selected policy directly requires it. |
| Compose deployment audiences | compose-api | `kustomize/config/compose-api-rke/api.env`; `kustomize/overlays/compose-api-local/auth0.env`; `tests/common/test_deployment_auth0_config.py` | Production uses `https://api.compose.cam.uchc.edu`; local uses `https://api.compose.local`; both use the BioSim tenant. | Preserve distinct audiences and rerun the existing deployment-config test after any config edit. |
| Production/local SPA policy | auth0-pulumi / platform | `biosim-platform/clients.py`: `auth0_biosim_platform`; `platform/frontend/.env.example`; `platform/kustomize/config/*/frontend.env` | Pulumi source allows only `https://biosim.biosimulations.org` and `https://biosim.cam.uchc.edu`; the local template uses `http://localhost:4200` with the production SPA client ID; live inventory still has localhost callback/logout entries. | Do not silently add localhost to the shared production client. Prefer an explicitly isolated local client or obtain a documented security exception. |
| Browser callback/session | platform | `platform/frontend/app/plugins/auth0.client.ts`; `frontend/nuxt.config.ts` and `.env` conventions | Auth0 Vue uses `redirect_uri: window.location.origin`, `useRefreshTokens: true`, `cacheLocation: 'localstorage'`, and the configured BioSim API audience. | A local client must be configured for the exact local origin and the same supported authorization-code/refresh-token flow. |
| First-login role assignment | auth0-pulumi | `biosim-platform/actions/biosim_roles.js::onExecutePostLogin`; `actions.py`; `tests/test_roles_action.py` | The Action assigns `user` through the Management API when the user has no roles, writes roles/email claims, and catches assignment failures without rejecting login. | Offline behavior is covered; live first-login and persisted-role verification remain required. |
| Action Management grant | auth0-pulumi | `biosim-platform/clients.py::biosim_roles_action_m2m`; `clientGrants.py::biosim_roles_action_management_grant` | Dedicated client is `client_credentials` only and has exactly `update:users`. | Keep separate from the Platform backend client; do not add deletion or unrelated scopes here. |
| Platform profile/deletion calls | platform | `backend/biosim_server/users/router.py`: `get_me`, `update_me`, `delete_me`, `reset_my_password`; `common/auth/auth0_management.py` | Backend calls Management API GET/PATCH/DELETE user and password-change-ticket endpoints using one server-only M2M credential. `delete_me` invokes `delete_auth0_user(user.sub)`. | Required scopes must be derived from these call sites, not from the Action grant. |
| Platform Management configuration | platform | `backend/biosim_server/config.py::Auth0Settings`; `backend/.env.example`; `kustomize/README-config.md` | `AUTH0_MANAGEMENT_CLIENT_ID/SECRET` are optional sealed-secret settings; docs state `update:users`, `delete:users`, and `create:user_tickets` use. | Add `delete:users` only to the verified backend M2M grant, and preserve secret-only handling. |
| Compose user-delegated grant | auth0-pulumi | `compose-api/clientGrants.py::biosim_spa_compose_user_grant` | Production BioSim SPA receives a `subject_type="user"` grant for the Compose production audience with no scopes. | Keep this grant unchanged; no frontend Compose call site exists to validate it end to end. |
| Pulumi ownership/order | auth0-pulumi | `biosim-platform/__main__.py`, `compose-api/clientGrants.py`, both stack YAML files | BioSim owns the tenant, SPA, roles, Action, and shared ESC environment; Compose reads `biosim_spa_client_id` through `StackReference`. | Apply BioSim before Compose whenever the SPA output or client changes. Review full previews; never apply an unexplained change. |

## 4. Current Auth0 contract matrix

| Contract | Producer/source of truth | Consumer | Current value/behavior | Desired value/behavior | Compatibility |
|---|---|---|---|---|---|
| Tenant | BioSim Pulumi ESC and `biosim-platform/tenant.py` | Compose verifier, Platform frontend/backend, Pulumi provider | `dev-bu7yo7484tyxu6a1.us.auth0.com` | Unchanged | Compatible |
| Issuer | Auth0 tenant convention; `compose_api/authentication.py` and Platform auth settings | Compose and Platform JWT verification | `https://dev-bu7yo7484tyxu6a1.us.auth0.com/` | Unchanged | Compatible |
| Compose production audience | `auth0-pulumi/compose-api/resourceServers.py` and RKE env | Compose verifier and future callers | `https://api.compose.cam.uchc.edu` | Unchanged | Compatible |
| Compose local audience | `compose-api/resourceServers.py` and local overlay | Local Compose verifier/test client | `https://api.compose.local` | Unchanged | Compatible |
| BioSim SPA client | `biosim-platform/clients.py`, exported by `__main__.py` | BioSim frontend and Compose StackReference | One production SPA client, currently also referenced by the local template | Keep production client production-only; use a distinct local client if approved | **Blocked by policy decision** |
| Production callbacks/logout/origins | `auth0_biosim_platform`; GKE/RKE frontend env | Auth0-hosted login/logout and browser | GKE and RKE source URLs are present; RKE source correction is not applied live | Exact deployed HTTPS origins in the production client | Source ready; live apply intentionally skipped |
| Local callback/logout/origins | Platform `.env.example`; SPA client policy | Local browser login | Local template requests `http://localhost:4200`; Pulumi source excludes localhost and live state differs | Isolated local client with exact loopback entries, or a security-approved narrow exception | **Blocked by policy decision** |
| User token flow | BioSim SPA client/grant and post-login Action | Platform backend; Compose accepts compatible JWTs | Authorization code/refresh token flow; Action adds roles/email claims | Verify with an authorized browser session | Static/offline only |
| Roles | `biosim-platform/roles.py` and `actions/biosim_roles.js` | Platform authorization and Compose principal | `user`, `admin`, `publisher`; Action assigns `user` on first login | Persisted `user` role and first token claim verified live | Offline pass; live verification required |
| Action Management grant | `biosim-platform/clientGrants.py` | BioSim Roles Action | `update:users` only | Same | Compatible; do not broaden |
| Platform Management grant | Existing Auth0 tenant grant consumed by Platform env | Platform Management client | Audit inventory: lacks `delete:users`; includes profile/ticket and unrelated client/role administration scopes | Exact union of verified Platform workflows, including `delete:users` if deletion remains enabled | **Blocked pending ownership/scope review** |
| Account deletion | Platform `delete_me` → `delete_auth0_user` | Auth0 `/api/v2/users/{id}` | Intended, but current grant cannot authorize it | Return 204 only after successful authorized deletion; otherwise fail explicitly | Blocked until grant/app design is applied |
| Session renewal | Platform frontend plugin and tenant/session settings | Browser session | Refresh tokens enabled in source/live configuration; not browser-tested | Silent refresh succeeds and restored session remains authenticated | Requires live verification |

## 5. Decision: local callback/security policy

### Current behavior

`platform/frontend/.env.example` uses `NUXT_PUBLIC_BASE_URL=http://localhost:4200` and the
production SPA client ID. The frontend plugin sets `redirect_uri` from
`window.location.origin`, so local login requests a loopback callback. The audit’s read-only
tenant inventory found localhost callback/logout entries live, while
`auth0-pulumi/biosim-platform/clients.py::auth0_biosim_platform` deliberately declares only
the two deployed HTTPS origins and documents removal of localhost as an Auth0 security-check
remediation. The same Pulumi source controls callback URLs, logout URLs, web origins, and
allowed origins for the shared production SPA.

### Conflict

The local development configuration requests `http://localhost:4200` on the shared production
SPA, but the Pulumi security policy excludes non-HTTPS localhost URLs. Applying the current
source as-is would remove live localhost entries; adding localhost to the shared SPA would
weaken the production client’s allowlists and reverse the documented security remediation.
This is a real policy conflict, not a missing string.

### Security considerations

The callback and logout allowlists are redirect destinations, not merely CORS settings. A
production client shared with deployed applications should not gain a broad local-development
surface for convenience. The repository already separates production and local Compose API
audiences, and the Pulumi README describes client ownership and protected resources; those
patterns support environment isolation. Any exception must be exact (`http://localhost:4200`,
not a wildcard), limited to a disposable development client, and approved by the tenant/security
owner.

### Options considered

1. **Recommended: dedicated local SPA client.** Add a separate protected `app_type="spa"`
   client in `biosim-platform/clients.py` with authorization-code and refresh-token grants,
   exact loopback callback/logout/web/allowed origins, and a distinct exported output or
   documented local client ID. Point only `platform/frontend/.env.example` (and any local
   runtime config) at it. Authorize that client for the BioSim API through the existing
   grant ownership mechanism after inventorying the current grant. Keep the production client
   HTTPS-only.
2. **Narrow shared-client exception.** Add only the exact loopback values to
   `auth0_biosim_platform`, update tests and accept the security tradeoff. This is smaller in
   code but conflicts with the explicit security-remediation rationale and is not recommended
   without written security approval.
3. **HTTPS local development.** Use a locally trusted HTTPS hostname/certificate and a
   dedicated client or exact HTTPS entries. This preserves the HTTPS policy but requires a
   local ingress/certificate workflow that was not found in the reviewed repositories; it is
   viable only if the Platform team already has that workflow.

### Planned resolution

Use option 1 unless the security owner explicitly chooses option 2 or an existing HTTPS-local
workflow proves option 3 is already supported. Before implementation, record the decision and
the exact local origin(s). Do not apply either source or live configuration until the decision
is recorded.

Implementation of option 1 should:

1. Add a separately named local SPA resource in `auth0-pulumi/biosim-platform/clients.py`,
   imported by `__main__.py`, with `protect=True`, no `client_credentials`, and exact
   `http://localhost:4200` callback/logout/web/allowed-origin entries.
2. Export its client ID under a stable, clearly local output name if Pulumi output is the
   supported configuration path; otherwise document the non-secret ID in the local example
   without putting credentials in source.
3. Determine who owns the BioSim API client grant for the local SPA. If this stack owns it,
   declare it in `biosim-platform/clientGrants.py` and add an explicit test; if it is
   intentionally dashboard-managed, record that ownership and validate it read-only before
   applying.
4. Change only local Platform frontend configuration to use the local client ID. Keep GKE/RKE
   frontend env files on the production client ID.
5. Add structural tests for the local client’s exact URLs, grant types, output, and separation
   from the production client. Keep existing production URL tests unchanged.

### Files/resources affected

- `auth0-pulumi/biosim-platform/clients.py`: new local SPA resource, if option 1 is selected.
- `auth0-pulumi/biosim-platform/__main__.py`: import/export wiring.
- `auth0-pulumi/biosim-platform/clientGrants.py`: only if the local SPA API grant is brought
  under Pulumi ownership.
- `auth0-pulumi/biosim-platform/tests/test_program_structure.py` and
  `tests/test_client_grants.py`: exact contract tests.
- `platform/frontend/.env.example` and any local-only runtime configuration: local client ID.
- `platform/frontend/.env` remains git-ignored and must never be added to the plan’s diff.
- `compose-api` source should not change for this decision unless a verified browser call path
  later requires a specific CORS origin; the skipped frontend-to-Compose path is not such a
  requirement.

## 6. Decision: Management API least privilege

### Verified consumers

The Platform backend’s `platform/backend/biosim_server/common/auth/auth0_management.py`
performs:

- `GET /api/v2/users/{id}` in `get_auth0_user` for best-effort profile enrichment;
- `PATCH /api/v2/users/{id}` in `update_auth0_user` for profile updates;
- `DELETE /api/v2/users/{id}` in `delete_auth0_user` for `DELETE /api/v1/me`;
- `POST /api/v2/tickets/password-change` in `create_password_change_ticket` for the hosted
  password-reset endpoint.

The corresponding router call sites are `get_me`, `update_me`, `delete_me`, and
`reset_my_password` in `platform/backend/biosim_server/users/router.py`. The Action has a
different client and only assigns roles; it must not share this server grant.

### Permissions table

The exact live scope list must be captured by an authorized, redacted inventory before changing
it. The audit established the following decision table without reproducing any secret:

| Scope | Current? | Required after change? | Consumer / workflow | Evidence | Action |
|---|---:|---:|---|---|---|
| `read:users` (or equivalent read permission) | Present in the audited live grant’s profile-related set; verify exact spelling | Yes if `get_me` profile enrichment remains enabled | `get_auth0_user` | `auth0_management.py::get_auth0_user`; `users/router.py::_build_profile` | Retain only if the application continues this enrichment; otherwise remove in a separate behavior decision. |
| `update:users` | Present | Yes | `update_me` PATCH | `update_auth0_user`; `users/router.py::update_me` | Retain. |
| `delete:users` | **Absent** | Yes if `delete_me` remains supported | `delete_me` DELETE | `delete_auth0_user`; `users/router.py::delete_me` | Add to the backend grant, or explicitly disable/redesign account deletion before enabling the route. Do not claim deletion works without this. |
| `create:user_tickets` | Present/expected for the ticket workflow; verify live | Yes if password reset remains enabled | `create_password_change_ticket` | `auth0_management.py`; backend docs and `.env.example` | Retain only when the endpoint is enabled and its client is configured; otherwise document the disabled workflow and remove only with owner approval. |
| Client administration scopes | Present in the audited live grant’s unrelated set; exact names require read-only inventory | No evidence in Platform call sites | No `clients` Management API call in the reviewed Platform backend | `rg` call-site inventory; audit finding | Remove from this grant only after confirming no other service/process uses this client. If another consumer exists, split clients/grants rather than breaking it. |
| Role administration scopes | Present in the audited live grant’s unrelated set; exact names require read-only inventory | No for the Platform backend’s reviewed calls | Role assignment belongs to the separate BioSim Roles Action client | `biosim_roles.js`, `biosim_roles_action_management_grant` | Remove from this grant after owner/consumer confirmation; never move them to the backend client merely to make deletion work. |
| Any other scope | Verify | Only with a named call site and owner | Not established by repository evidence | Live grant inventory plus repository search | Stop and resolve ownership before removal. |

The target is the least-privilege union of the workflows actually enabled on this backend:
profile read/update, `delete:users` for account deletion, and `create:user_tickets` for hosted
password reset. If password reset or profile enrichment is intentionally disabled, that must be
an explicit product decision with corresponding configuration/tests, not an opportunistic scope
removal. The dedicated Action grant remains exactly `update:users`.

### Required ownership decision

The backend M2M client is configured through Platform sealed-secret settings and its grant is not
declared in the reviewed `auth0-pulumi` `clientGrants.py`. Before narrowing it, identify the live
client by the non-secret client ID from the deployed configuration, inventory all repositories and
workflows using it, and identify the Auth0/Pulumi owner. If the grant is brought under Pulumi
ownership, import/adopt the existing grant rather than declaring a duplicate. If another
consumer needs the broader scopes, create a separate least-privilege client for Platform
account/profile operations and leave the other client unchanged until migration is complete.

## 7. Detailed implementation plan

### Phase 1 — Record decisions and establish a redacted baseline

1. **Objective:** prevent an implementation from guessing at security policy or grant ownership.
2. **Repositories:** `auth0-pulumi`, `platform`, `compose-api` audit evidence.
3. **Actions:** obtain security-owner decision on dedicated local SPA versus exact exception;
   capture a redacted inventory of the production SPA allowlists and backend M2M grant scopes;
   identify the grant owner and every consumer of the backend client ID. Do not copy client
   secrets, access tokens, or sealed-secret plaintext into files or tickets.
4. **Validation:** record current stack selection, `pulumi stack export` resource identities,
   `pulumi config get auth0:domain` and non-secret client IDs only; use Auth0 read-only APIs
   through the approved operator path.
5. **Acceptance:** the chosen local policy, backend M2M client owner, exact current scopes, and
   intended retained scopes are written down. If any other consumer is found, split the client
   design before changing a grant.
6. **Risks/rollback:** an incomplete inventory can revoke another service’s access. Stop rather
   than narrow a shared grant; no rollback is needed because this phase is read-only.

### Phase 2 — Implement the local callback policy

1. **Objective:** make local browser login work without weakening the production SPA.
2. **Repository/files:** primarily `auth0-pulumi/biosim-platform/clients.py`,
   `__main__.py`, optional `clientGrants.py` and tests; local-only Platform frontend config.
3. **Behavior:** for the recommended dedicated-client option, create the protected local SPA
   with exact loopback entries and authorization-code/refresh-token grants; export or document
   its non-secret client ID; configure only local frontend defaults to use it. Keep production
   callbacks/logout/web origins and client ID unchanged.
4. **Tests:** extend `test_program_structure.py` for exact local URL sets, no
   `client_credentials`, protected resource, and production/local client separation. Extend
   `tests/test_client_grants.py` only if a Pulumi-owned local API grant is added. Add a Platform
   config test if the repository’s existing test convention covers local client wiring.
5. **Commands:** `uv run --directory biosim-platform python -m pytest tests -m "not live" -q`;
   `uv run --directory compose-api python -m pytest tests -q`; Node Action tests are unchanged.
6. **Expected result:** offline tests prove the production client remains HTTPS-only and the
   local client is exact and isolated.
7. **Dependencies/rollback:** Phase 1 policy decision and grant ownership come first. Roll back
   by removing only the new local client/output and restoring local config to the prior known
   value; do not add localhost to production as a rollback shortcut.

### Phase 3 — Reconcile the Platform Management grant

1. **Objective:** make account deletion truthful and reduce the backend grant to justified
   permissions.
2. **Repository/files:** Platform documentation/config as needed; the authoritative
   `auth0-pulumi` grant owner or an approved Auth0 change path. `platform/backend` code should
   not be changed merely to hide a missing permission.
3. **Behavior:** add `delete:users` to the backend client grant if `delete_me` remains enabled;
   retain `update:users` and only the read/ticket scopes backed by active call sites; remove
   client/role administration scopes only after the phase-1 inventory proves they are unused.
   If shared use is discovered, create/switch to a separate backend M2M client instead of
   narrowing the shared one.
4. **Tests:** add a grant contract test in the owning Pulumi project that asserts the complete
   intended set; add/update Platform Management API tests to assert DELETE success and
   insufficient-scope failure mapping (502) without live credentials. Keep the existing Action
   test asserting `["update:users"]`.
5. **Commands:** run the owning offline Pulumi suite, Platform targeted auth/user tests, backend
   Ruff/mypy, and the relevant full non-integration backend suite.
6. **Expected result:** every retained scope has a named consumer; deletion is either supported
   by `delete:users` or explicitly disabled by a separate product decision.
7. **Risks/rollback:** removing a scope used outside the repository causes provider 403s.
   Roll back through the owning IaC grant/client or restore the previous grant only after the
   owner confirms the exact prior scope set. Never paste or commit the secret.

### Phase 4 — Local validation and refreshed previews

1. **Objective:** prove source and infrastructure intent before any live mutation.
2. **Commands:** run the repository gates in the validation matrix; from
   `auth0-pulumi/biosim-platform`, select `biosim-platform-auth0` and run
   `pulumi preview --refresh --non-interactive --diff`; from
   `auth0-pulumi/compose-api`, select `compose-api-auth0` and run the same preview if its
   StackReference is affected. Run `pulumi preview --diff` again after any approved source
   adjustment.
3. **Expected result:** the preview contains only the selected local-client/grant changes and
   known pre-existing or explicitly approved drift (including the intentionally skipped RKE
   live application). No unexpected tenant, role, Action, resource-server, or unrelated client
   replacement appears.
4. **Stop condition:** stop and return to ownership review if a preview shows deletion/replacement,
   a second bootstrap client, changed production URLs, changed audiences, a different Action
   binding, unexplained tenant settings, or any resource unrelated to this plan.
5. **Rollback:** no apply has occurred; revise source or use a targeted, reviewed plan rather
   than suppressing a diff.

### Phase 5 — Authorized live apply

1. **Objective:** apply only reviewed infrastructure changes.
2. **Authorization:** obtain explicit approval from the Auth0/security owner and deployment
   owner. This phase mutates the Auth0 tenant and may change redirect behavior, client grants,
   and user-management capability.
3. **Order:** apply `biosim-platform` first when its client/output or tenant-owned grant changes.
   Apply `compose-api` afterward only if its StackReference or Compose grant actually changes.
   The exact approved command is `pulumi up --diff --non-interactive` from the selected project
   directory; it must not be run during this planning task.
4. **Post-apply checks:** confirm the intended resources and fields only through read-only
   inventory; verify the production client remains HTTPS-only, the local client has exact
   loopback entries, the Action client remains `client_credentials` plus `update:users`, and
   the backend grant has the approved exact set.
5. **Rollback:** use the previous reviewed IaC revision/stack state or a reviewed corrective
   change. Do not use an ad hoc dashboard edit that leaves source and tenant divergent.

### Phase 6 — Authorized browser/user smoke test

1. **Objective:** verify real Auth0 behavior not established by mocks or previews.
2. **Environment:** use a non-production/dev tenant and an explicitly authorized browser
   session. Test the deployed GKE/RKE environment whose callback allowlist is actually applied,
   or the approved local client if its local callback policy was implemented. Do not test the
   intentionally skipped RKE live application until its separate deployment dependency is
   authorized.
3. **Procedure:** follow the detailed procedure in section 11, capture only redacted evidence,
   and clean up according to the authorization.
4. **Expected result:** signup/sign-in, callback, first-login `user` role, token role claim,
   refresh renewal, logout, and (if approved) account deletion all behave as documented.
5. **Rollback:** stop user testing on any callback, role, token, or deletion anomaly; do not
   repeatedly retry deletion or create extra users while diagnosing.

### Phase 7 — Final gates and readiness review

1. Re-run the affected quality gates and refreshed previews after live changes.
2. Review `git status`, unstaged/staged diffs, generated files, secret patterns, and the complete
   preview output in both repositories. Do not include the audit file’s existing unrelated
   working-tree edits in a new change.
3. Mark ready for a separate commit/push decision only when all criteria in sections 15 and 16
   are satisfied.

## 8. Suggested sequencing

1. Record the local callback policy and Management-client ownership decision.
2. Inventory exact live allowlists, grant scopes, consumers, and current Pulumi state read-only.
3. Implement the isolated local client/configuration and grant contract, if selected.
4. Implement the approved Management grant ownership/scope change, including `delete:users`.
5. Run targeted/offline Compose, Pulumi, Platform backend, and frontend checks.
6. Run refreshed previews for the affected Pulumi projects; stop on unexplained changes.
7. Obtain explicit authorization for live Auth0/IaC mutations.
8. Apply BioSim first, then Compose only if its dependent output/grant changes.
9. Perform the authorized browser/user smoke test.
10. Re-run quality gates, refreshed previews, secret/diff checks, and the final readiness review.

Local/code-only and offline preview steps are safe to perform without tenant mutation. Applying
Pulumi, changing grants/clients, and creating or deleting a test user are live mutations and
require explicit authorization.

## 9. Test and validation matrix

| Test / check | Repository/environment | Purpose | Command or procedure | Expected result | Requires live mutation? |
|---|---|---|---|---|---:|
| Compose quality gate | compose-api | Lock, pre-commit/Ruff, strict mypy, deptry | `make check` | Pass | No |
| Compose auth regression | compose-api | JWT, JWKS, principal, malformed credentials | `uv run python -m pytest tests/api/test_authentication.py -q` | All focused auth tests pass | No |
| Compose non-SLURM suite | compose-api, Python 3.13 and 3.14 where CI requires | Regression coverage | `uv run python -m pytest tests -m "not slurm" -q` and the established Python 3.13 invocation | Existing audit baseline remains green | No |
| Compose deployment config | compose-api | Production/local domain and audience separation | `uv run python -m pytest tests/common/test_deployment_auth0_config.py -q` | Distinct expected audiences pass | No |
| OpenAPI/spec check | compose-api | Preserve optional bearer/client contract | `uv run python compose_api/api/openapi_spec.py`; `git diff --exit-code compose_api/api/spec/` | No unintended spec diff | No |
| Pulumi BioSim offline tests | auth0-pulumi | Resource wiring, URL policy, grants, protection | `uv run --directory biosim-platform python -m pytest tests -m "not live" -q` | All relevant offline tests pass | No |
| Pulumi Compose offline tests | auth0-pulumi | StackReference and complete Compose grant set | `uv run --directory compose-api python -m pytest tests -q` | All tests pass | No |
| Pulumi strict typing | auth0-pulumi | Type safety in separate projects | `MYPYPATH=biosim-platform uv run mypy biosim-platform` and `MYPYPATH=compose-api uv run mypy compose-api` | Pass | No |
| Action behavior | auth0-pulumi | First-login/admin/error handling offline | `node --test biosim-platform/actions/` | Existing Action tests plus any new cases pass | No |
| Platform auth destination tests | platform/frontend | Prevent bearer leakage and preserve configured API routing | `npm run test:auth` | Pass | No |
| Platform frontend gates | platform/frontend | Lint, typecheck, build | `npm run lint`; `npm run typecheck`; `npm run build` | Pass | No |
| Platform backend gates | platform/backend | Management/user/auth regression | Repository-established `uv run pytest`, Ruff, and mypy commands; target user/auth tests first | Pass | No |
| Grant consumer inventory | Auth0 read-only + all repositories | Prove scope ownership before removal | Search call sites, inspect deployment settings, and obtain redacted live grant inventory | Every retained scope has an owner; no hidden consumer | No |
| Refreshed Pulumi preview | auth0-pulumi affected project(s) | Confirm drift and intended resource changes | `pulumi preview --refresh --non-interactive --diff` from each selected project | Only understood/approved changes | No |
| Browser signup/sign-in | Authorized dev tenant/browser | Real Universal Login and token issuance | Section 11 procedure | Login succeeds; no unexpected redirect/error | Yes: user/session state |
| Callback | Authorized dev tenant/browser | Code/state exchange and app restoration | Observe redirect back to exact configured origin and authenticated app state | Correct callback, no mismatch error | Yes |
| First-login role | Authorized new test user | Verify Action assignment and first token | Decode token locally without recording it; inspect role via authorized backend/Admin view | `user` role persisted and claim present | Yes |
| Session renewal | Authorized browser | Verify refresh token/session restoration | Wait beyond access-token lifetime or use approved controlled expiry test; reload and call protected endpoint | Silent renewal succeeds without login loop | Yes |
| Account deletion | Authorized disposable test user only | Verify `delete:users` and 204 path | Call the Platform account-delete UI/API with explicit approval; verify user is gone | 204 and expected cleanup, no repeated retries | Yes |
| Final Git/diff review | both repositories | Prevent unrelated/secrets/generated changes | `git status --short --branch`, `git diff`, `git diff --cached`, `git diff --check` | Only intended files; no secrets | No |

## 10. Authorized live smoke-test procedure

**Do not execute this section until the security/deployment owner explicitly authorizes it.**
No credentials, passwords, access tokens, client secrets, or user identifiers belong in the
plan or captured evidence.

### Prerequisites

1. Use a designated dev/test tenant and the exact deployed frontend origin whose client
   allowlist was applied. Confirm whether the RKE live allowlist application is an external
   dependency; this plan does not implement it.
2. Obtain an authorized disposable test account or written authorization to use an existing
   non-production account. Creating a user is a live mutation; deletion/cleanup also requires
   explicit authorization.
3. Confirm the expected `user` role exists and the BioSim Roles Action is deployed, bound to
   post-login, and using the approved dedicated Action client.
4. Confirm the backend M2M grant has the approved scopes, including `delete:users` if deletion
   is in the test, and that secrets are mounted through the approved sealed-secret path.

### Ordered test

1. Open the exact frontend origin in a clean/private browser context and start **sign-in**.
   Confirm Auth0 redirects to the expected tenant and returns to the exact origin/path without
   a callback mismatch.
2. If signup is part of the approved flow, use the provider’s supported signup path with the
   disposable account. Verify the account only in the authorized tenant and do not record
   credentials.
3. On first login, capture a redacted browser/network result and decode the access-token
   payload locally without storing the token. Confirm issuer, expected BioSim audience,
   `https://api.biosimulations.org/roles` containing `user`, and the expected namespaced email
   claims. Do not send an ID token to an API.
4. Verify persistence through an authorized read-only tenant/admin view or the next login:
   the user retains `user` and the Action does not repeatedly need to assign it. If assignment
   fails, preserve the redacted Auth0/Action error and stop; do not manually patch the role
   while claiming the Action passed.
5. Call the Platform authenticated profile endpoint and, if approved, the relevant protected
   endpoint. Confirm the browser attaches the BioSim token only to the configured Platform API.
6. Exercise session renewal by waiting for or deliberately using the approved token-expiry
   boundary, reloading, and calling the authenticated endpoint. Confirm refresh succeeds,
   the app remains signed in, and no callback loop occurs.
7. Exercise logout and confirm the return destination is the exact allowlisted origin.
8. If and only if separately authorized, call account deletion once for the disposable user.
   Expect the documented 204 result, verify the user is no longer usable, and record whether
   downstream application data cleanup is expected or handled separately. Do not retry a
   deletion whose response is ambiguous.

### Failure evidence and cleanup

Capture timestamps, environment/origin, browser result, HTTP status, sanitized error text, and
resource/Action version identifiers. Never capture cookies, authorization headers, tokens,
passwords, client secrets, or full user PII. Remove local browser storage and clean up the
test user/state only as authorized. If a user was created and deletion is not approved or
fails, stop and hand off to the tenant owner rather than mutating it again.

## 11. Pulumi preview/apply checklist

### Before apply

- The local callback decision is documented and does not add localhost to the production client
  unless a security owner explicitly approved that exception.
- Backend Management client ownership and exact retained/removed scopes are documented.
- Offline tests and strict mypy pass in every changed Pulumi project.
- The relevant stack is selected from the correct project directory and ESC credentials resolve
  without printing secrets.
- The complete refreshed preview has been reviewed by the Auth0/security owner.
- No preview includes an unexplained resource replacement, deletion, tenant setting change,
  Action rebinding, audience change, or unrelated client/grant modification.
- Explicit authorization exists for live mutation.

### Preview

From each affected project directory:

```bash
pulumi stack select biosim-platform-auth0   # from auth0-pulumi/biosim-platform
pulumi preview --refresh --non-interactive --diff

pulumi stack select compose-api-auth0       # from auth0-pulumi/compose-api, only if affected
pulumi preview --refresh --non-interactive --diff
```

Use `pulumi config get auth0:domain` and `pulumi config get auth0:clientId` only for non-secret
diagnostics. Never print or place `auth0:clientSecret`, Action secrets, or backend secrets in
the plan.

### Expected resource changes

Depending on the selected design, the expected changes are limited to a new/updated local SPA
client and its explicitly owned API grant, plus the approved backend Management grant scope
change. The existing production SPA URLs, BioSim Roles Action source/binding, dedicated Action
grant, resource-server identifiers, tenant settings, and Compose production user grant should
remain unchanged.

### Unexpected-change stop condition

Stop immediately if preview contains an unrelated client/grant, removal of a production callback,
Action replacement/rebinding, tenant-wide setting drift, bootstrap-client change, audience
change, or a `readme`/output change that is not understood. Do not use `--target` to conceal
unrelated drift; use it only after a separately reviewed ownership decision.

### Apply

The eventual approved command is `pulumi up --diff --non-interactive` from the relevant project
directory, with BioSim applied before Compose when the SPA output changes. **Do not run it during
this planning task.** The source repository instructions explicitly warn that these commands
reconcile live Auth0 tenants.

### Post-apply verification

Re-run a read-only inventory, the relevant Pulumi preview, offline tests, and the authorized
browser smoke test. Confirm exact callback/logout/origin and grant scope values, then review
the resulting Git diff. A clean preview is necessary but not sufficient for live login/role
readiness.

## 12. Rollback strategy

| Failure | Recovery |
|---|---|
| Callback mismatch or login redirect failure | Stop browser testing. Restore the last reviewed client allowlist through the owning Pulumi source/stack, or correct the exact local-client URL. Do not add broad wildcards or edit production manually without reconciling source. |
| Local development becomes unusable | Revert only local frontend client configuration to the last known client; keep production client policy unchanged. If the new local client is faulty, remove it through a reviewed protected-resource change after confirming no user dependency. |
| Management API returns insufficient scope | Do not retry destructive operations. Inspect the approved grant/client ID and token audience, then restore/add only the specifically required scope through the owner. |
| First-login role assignment fails | Preserve sanitized Action logs/status, verify Action secret names/client grant/role ID, and stop. The Action is intentionally non-fatal; do not manually assign roles while diagnosing unless separately authorized. |
| Account deletion fails or is ambiguous | Treat the account as possibly deleted; do not repeat the request. Verify status through an authorized read-only path and hand off cleanup to the tenant owner. |
| Pulumi applies incorrect configuration | Stop further applies, export/read the stack state, compare with the approved preview, and make a reviewed corrective IaC change. Do not use `pulumi destroy`; protected resources and live users must not be removed casually. |

## 13. Risks and unresolved questions

| Classification | Question/risk | Evidence checked | Required answer / blocker |
|---|---|---|---|
| Security decision | Should localhost be isolated to a new SPA client or explicitly allowed on the shared production client? | Pulumi source excludes localhost as security remediation; Platform local env requires it; live state still contains it. | Auth0/security owner must choose. Blocks local-client implementation and apply. |
| Ownership | Who owns the existing Platform backend M2M grant, and does any other service use its broad scopes? | Platform call sites and repository search; audit found client/role administration scopes but no local consumers. | Live inventory plus service-owner confirmation. Blocks scope removal. |
| Product behavior | Is account deletion intended to remain enabled when Management credentials are mounted? | `delete_me` and `delete_auth0_user` exist; deployment docs currently say credentials are unset and routes return 503. | Platform owner must retain deletion and add `delete:users`, or explicitly disable/redesign it. Blocks claiming deletion readiness. |
| External dependency | RKE callback/logout source correction is not applied live. | Audit and preview. | Separate deployment owner; intentionally skipped here, but it blocks an RKE live-login claim. |
| Live verification | No authorized browser session or disposable user was provided. | Audit performed read-only inventory and offline tests only. | Explicit authorization and test-user procedure. Blocks signup/role/session claims. |
| Deployment drift | Refreshed preview previously showed two updates, including SPA drift and Action-client grant-type drift. | Audit: live SPA localhost/RKE mismatch and live Action client still had `refresh_token`. | Re-run after source decisions; unexplained updates are a stop condition. |
| Cross-service CORS | Compose `APP_ORIGINS` does not currently include Platform origins. | `compose_api/api/main.py`, audit notes. | Do not add as part of skipped frontend-to-Compose work; revisit only if a concrete Compose browser call site is introduced. |

## 14. Definition of done

The remaining work is complete only when all applicable criteria are true:

- The local callback policy is explicitly decided, production security is not weakened
  unintentionally, and the implemented client/origin arrangement matches that decision.
- The backend Management API client and grant owner are documented; every retained scope has a
  verified consumer; unrelated client/role scopes are removed or separately owned.
- `delete:users` is present for the actual backend client if account deletion remains enabled,
  and DELETE behavior has a targeted regression test plus an authorized live verification if
  that workflow is included.
- Existing `update:users`-only Action grant and first-login Action contract remain intact.
- Relevant Compose, Platform, and Pulumi tests, type checks, lint/build gates, and focused
  authentication tests pass.
- Refreshed previews contain only understood and approved changes; no unexplained resource
  replacement, tenant drift, secret change, or generated artifact is present.
- Approved infrastructure changes have been applied only after authorization and in the correct
  BioSim-before-Compose order.
- Authorized signup/sign-in, callback, first-login `user` role assignment, session renewal, and
  logout have been exercised. Account deletion is verified only if explicitly included.
- The intentionally skipped RKE live application and frontend-to-Compose call-site limitation
  are clearly recorded and not falsely represented as verified.
- Final diffs contain only intended files; no credentials, tokens, secrets, accidental generated
  files, or unrelated working-tree changes are included.

## 15. Push-readiness checklist

Before a separate commit/push decision, the reviewer should be able to check every applicable
item:

- [ ] Local callback/security decision is recorded and approved.
- [ ] Expected files/resources changed only; production and local client ownership is clear.
- [ ] Management API consumer inventory and least-privilege scope decision are recorded.
- [ ] `delete:users` is supported or account deletion is explicitly disabled/redesigned.
- [ ] Compose authentication hardening remains untouched except for an evidence-backed dependent
      change.
- [ ] Targeted tests, `make check`, relevant Python-version suites, Pulumi offline tests,
      frontend auth tests, backend quality gates, and Node Action tests pass.
- [ ] Refreshed non-destructive Pulumi previews were reviewed in full and contain only approved
      changes.
- [ ] Any live apply was explicitly authorized and verified; no `pulumi up` was run as part of
      this planning task.
- [ ] Authorized browser smoke test covers signup/sign-in where supported, callback, role
      assignment, renewal, logout, and deletion only when approved.
- [ ] RKE live application and frontend-to-Compose verification are marked as skipped rather
      than falsely passed.
- [ ] Secret-pattern scan and `git diff --check` are clean.
- [ ] `git status --short --branch`, unstaged diff, staged diff, and generated-file review show
      no unrelated changes.
- [ ] No accidental Pulumi state/config mutation, secret exposure, commit, push, deployment,
      user mutation, or unexplained blocker remains.

## 16. Execution record (2026-09-25)

Executed by Claude Code. Live mutations were authorized by the owner in-session. Tokens and secrets were never printed
or written to files. Live reads used the Pulumi operator client through the Pulumi ESC environment, read-only.

### Phase 1: decisions and redacted baseline (done)

| Item | Decision / evidence |
|---|---|
| Local callback policy | **Option 1, a dedicated local SPA**, per this plan's recommendation. The production SPA stays HTTPS-only. |
| Backend Management client | `e3wDHGNMdIaFU7jOoeNlzXtqjB8L8MA0` = `biosim_management_api_m2m`, already owned by the `biosim-platform` stack. Its only code consumer is `platform/backend` (`AUTH0_MANAGEMENT_CLIENT_ID`); search covered every repository under `~/Github`. |
| Live Management grant (before) | `cgr_L7YmXK5in5sA2Fy0`, 11 scopes: `create:clients, create:role_members, create:user_tickets, read:client_grants, read:clients, read:resource_servers, read:users, update:client_grants, update:clients, update:roles, update:users`. **No `delete:users`.** |
| Usage evidence | The tenant log window (~17 h, 2026-09-25 01:31–18:30 UTC) shows **zero** events for this client. |
| Scope decision | **Owner decision: add `delete:users` and keep all existing scopes.** The 8 scopes without a call site are retained by decision (listed in `clientGrants.py: RETAINED_WITHOUT_CALL_SITE`), not proven necessary. |
| Account deletion | Kept enabled (`delete_me`, `README-config.md`), so `delete:users` was added. |
| Out of scope, recorded | This client's second grant, `cgr_DcszAz5y8nAq4WHl` (BioSim API, `assign:users read:users update:users`), has no code consumer. Left unchanged. |

### Phase 2: local callback policy (done)

- `auth0-pulumi`:
  - `clients.py` adds `auth0_biosim_platform_local` (SPA, exact `http://localhost:4200` ×4, `authorization_code` +
    `refresh_token`, protected) and `auth0_biosim_platform_local_credentials` (`authentication_method="none"`).
  - `clientGrants.py` adds `biosim_platform_local_spa_user_grant` (user, BioSim API, `allow_all_scopes`, mirroring the
    production SPA's live grant `cgr_V1TbUuC6s1CpieZH`).
  - `__main__.py` exports `biosim_spa_local_client_id`.
- `platform/frontend/.env.example` now uses the local client `WFNcITp0mjLiNLE9FltmMQmrglO8UCrg`. The GKE and RKE
  ConfigMaps are unchanged (production SPA).
- Tests: exact loopback URLs, public PKCE client, production stays HTTPS-only and separate, and protection is checked in
  the declaring modules (the pre-existing `__main__.py` protection check is vacuous). Mutation checks: localhost on
  production, a confidential local client, and an unprotected local client each fail the suite.

### Phase 3: Management grant (done, to the owner-chosen scope set)

- `clientGrants.py: biosim_management_api_m2m_management_grant` adopts `cgr_L7YmXK5in5sA2Fy0` via `pulumi import`
  (never created). Scopes are the 4 call-site scopes (`read:users`, `update:users`, `delete:users`,
  `create:user_tickets`) plus the 8 retained ones.
- `tests/test_client_grants.py` pins the exact 12-scope set, and that the Action grant is still `update:users` only.
- `platform/backend/tests/users/test_delete_account_management_scope.py` runs the real `delete_auth0_user` against a
  scripted Auth0. It checks that a successful delete returns 204, and that a `403 insufficient_scope` becomes an
  explicit 502 after exactly one attempt, with no token or secret in the response.

### Phase 4: validation and previews (done)

Offline gates passed. The refreshed preview showed 7 changes: 4 creates (local SPA, credentials, local grant,
Management grant) and 3 updates (production SPA HTTPS-only: `+RKE`, `-localhost`; the Action `email_verified` fix; the
Action client's stray `refresh_token`). No deletions, replacements, audience changes or rebinding. After the import,
the Management grant previewed as an update whose only net change was `+delete:users`.

### Phase 5: live apply (done)

- Order: `pulumi import` (state only), then `pulumi up` (3 created, 4 updated), then `pulumi up --refresh` (1 updated:
  the Action client's `grantTypes`, which a plain up couldn't see).
- Read-only post-apply inventory:
  - The production SPA's callbacks, logout, web and allowed origins are exactly the GKE and RKE HTTPS origins. The IdP
    login URI is preserved.
  - The local SPA is exactly `http://localhost:4200`, with auth method `none`.
  - The Action client is `client_credentials` only, with a grant of `update:users` only.
  - The backend grant has 12 scopes, including `delete:users`.
  - The deployed Action is `async` and stamps `email_verified`, with a single post-login binding.
- compose-api is unaffected (7 unchanged). Final refreshed previews: biosim-platform **18 unchanged** (only the
  `readme` output text differs), compose-api **7 unchanged**.

### Phase 6: smoke test (done within the authorized scope: the owner's existing account, GKE)

| Check | Result |
|---|---|
| Session restoration | Pass. Silent authentication (tenant log `ssa` at 18:43 UTC) restored the session with no prompt |
| Token (issued after the apply) | Pass. `iss` is the tenant; `aud` is the BioSim API plus userinfo; `azp` is the production SPA; `roles=["user"]` on access and ID tokens; `email_verified=true`; email claim present |
| Persisted role | Pass. The account (SHA-256 fingerprint `3a-b4-01-a6-a6`) is a member of `user`, 1 of 4 |
| Platform API | Pass. `GET /api/v1/me`: no token 401, valid token 200, garbage token 401 |
| Logout | Pass. Returned to `https://biosim.biosimulations.org/` |
| Sign-in initiation | Pass. Universal Login on the tenant for the production SPA, with no mismatch |
| Local policy (live) | Pass. The local SPA with a `localhost:4200` redirect reaches its login page; the production SPA with the same redirect gets `unauthorized_client`, "Callback URL mismatch" |
| Not exercised | New-user **sign-up** and **first-login assignment for a brand-new user** (no new user may be created); **refresh-token** renewal (the deployed build uses in-memory tokens and silent authentication, with no `offline_access` in scope); **account deletion** (no disposable user); **RKE live login** (`biosim.cam.uchc.edu` returns NXDOMAIN from this network) |
| Side finding | The tenant error page `https://biosim.biosimulations.org/auth/error` returns a Nuxt 404 on the deployed front end (pre-existing; platform-side) |

### Phase 7: final gates (done)

compose-api: `make check`; auth and deployment tests 70 passed; spec unchanged. `auth0-pulumi`: mypy on 3 stacks; 21 +
4 offline tests; 8 Node tests; `uv lock --check`. Platform front end: `test:auth` 4 passed; lint. Platform back end:
the new deletion tests plus the router tests (21 passed), ruff and mypy; full suite re-run in this phase. `git diff
--check` and a credential-pattern scan are clean in all three repositories, and nothing is staged. Nothing was committed
or pushed.

### Checklist (section 15) status

- [x] Local callback/security decision recorded (option 1, by the owner's instruction to execute this plan).
- [x] Only the expected files and resources changed; production and local client ownership is clear.
- [x] Management API consumer inventory and scope decision recorded (owner-retained scopes documented as such).
- [x] `delete:users` is supported (live grant verified; offline regression test).
- [x] Compose authentication hardening untouched.
- [x] Targeted tests, `make check`, Pulumi offline tests, front-end auth tests, back-end gates and Node tests pass.
- [x] Refreshed previews reviewed in full; only approved changes, and no drift after apply.
- [x] Live applies explicitly authorized and verified read-only afterwards.
- [ ] Browser smoke test covered sign-in, callback, role, renewal (silent) and logout on GKE, but **not sign-up, a new
      user's first login, refresh-token renewal, or deletion**. These need a disposable test user.
- [x] RKE live application recorded: allowlists applied and verified in the tenant; live RKE login not reachable from
      here.
- [x] Secret scan and `git diff --check` clean.
- [x] No unrelated staged changes. The working trees contain pre-existing user work, listed in the final report.
- [ ] **The applied `auth0-pulumi` source is uncommitted.** Commit it before any other `pulumi up`, or a later apply
      from another checkout will revert the tenant.
