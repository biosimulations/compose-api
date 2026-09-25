# Auth0 cross-repository audit — 2026-09-25

## 1. Executive result

Implementation-plan completion: BLOCKED
Cross-repository Auth0 compatibility: PARTIALLY VERIFIED
Push readiness: NOT READY TO PUSH

Local remediation and automated checks substantially validate the intended optional Compose authentication contract. They do **not** establish all-environment/live-login readiness. RKE URL corrections are unapplied, local callback policy conflicts with the live tenant, the Platform Management client lacks the account-deletion privilege, and first-login/admin flows were not exercised with real users.

No commits, pushes, infrastructure applies, or live-user mutations were performed. Auth0 access was limited to obtaining a Management token using existing configured credentials and read-only resource inventory; tokens/secrets were never written into this report.

## 2. Repository baseline

| Repository | Branch | Starting and ending HEAD | Starting tree |
|---|---|---|---|
| `/Users/novrusshehaj/Github/UCHC/compose-api` | `feature/auth0-implementation` | `ebb28c708b244fde64e14c3a853e06001a87afea` | Two unstaged edits: roles plan and .gitignore; no staged edits |
| `/Users/novrusshehaj/Github/UCHC/auth0-pulumi` | `feature/compose-api-user-access` | `429c24638019af7c83429b65c0ee148044bb7cd3` | Clean |
| `/Users/novrusshehaj/Github/UCHC/platform` | `chore/api-improvements` | `0d408205e1a962cadcafbb44b0b4c17dab6fd31d` | 31 modified tracked files, 9 untracked files; no staged edits |

Verified remotes: biosimulations/compose-api, UCHHPC/auth0-pulumi, biosimulations/platform. All origin/HEAD references resolve to main. Baseline diffs/status/HEAD/remotes/history were captured under `/tmp/auth0-cross-repo-audit/` before edits. Full pre-existing Platform file inventory appears below. No pre-existing file changes are attributed to this audit.

Tooling: Compose uses uv, Python 3.13/3.14, pytest, pre-commit/Ruff, strict mypy, deptry and MkDocs. Pulumi is a uv workspace with distinct biosim-platform, compose-api and vcell projects, Python 3.14, mocked pytest, Node Action tests and mypy. Platform uses uv/pytest/Ruff/mypy for backend and npm/Nuxt/ESLint/vue-tsc for frontend; CI uses Node 24. Local Node is 26.9.0; local Python is 3.14.7 and isolated validation also uses 3.13.15.

History reviewed: Compose optional auth (`e2afd01`), rotation/principal fix (`0268dcb`), environment wiring (`9a64a9e`), role derivation (`ebb28c7`); Pulumi SDK/secret-name fixes, async Action handler (`34ad856`), SPA export (`4288a04`) and grant (`429c246`); Platform global fetch interception (`1c07c13`) and existing backend working-tree changes. The global token leak predates this audit. Generated client response drift also predates this audit.

## 3. Complete implementation-plan ledger

Sources are sections of `.github/AUTH0_IMPLEMENTATION_PLAN.md` for AUTH0 rows and `.agents/AUTH0_ROLES_IMPLEMENTATION_PLAN.md` for ROLES rows. Historical findings/proposed snippets are interpreted against later explicit decisions. Repeated requirements cross-reference the same atomic row rather than being counted twice. PASS refers only to the stated acceptance condition/evidence tier; separate live gates remain BLOCKED.

Plan discrepancies resolved without inventing policy:
- The final health/version decision supersedes earlier conditional 401 language; both ignore credentials.
- Approved non-secret audiences must be checked in despite an older sentence saying not to commit a real audience.
- Global optional OpenAPI security preserves generated Client compatibility; per-operation security is deliberately absent.
- Actual Action SDK is 4.3.1 and existing secret names are M2M_CLIENT_ID/M2M_CLIENT_SECRET/DEFAULT_ROLE_ID; example 4.0.0 and renamed secrets were placeholders.
- Roles plan's header/deployment narrative and its old verification table disagree. Current live evidence is reported separately, not inferred from checkboxes.
- Commits, user creation/deletion and pulumi up in historical plan instructions are superseded by this task's explicit prohibitions.

| ID | Plan source | Requirement | Acceptance condition | Implementation evidence | Test/verification evidence | Status | Notes |
|---|---|---|---|---|---|---|---|
| AUTH0-001 | Goals; behavior; acceptance 1–3 | Preserve anonymous use, without signup/login | Absent header returns None; public requests continue | compose_api/authentication.py::_parse_bearer_token | tests/api/test_authentication.py::test_no_header_is_anonymous; test_catalog_route_anonymous_and_authenticated | PASS | — |
| AUTH0-002 | Behavior; acceptance 4 | Propagate verified identity | Actual handler receives immutable principal | compose_api/api/routers/{compute,curated,results,simulation}.py | tests/api/test_authentication.py::test_every_active_handler_receives_the_principal; test_active_handler_sees_the_verified_principal | PASS | — |
| AUTH0-003 | Behavior; acceptance 5 | Never downgrade bad credentials | 401 before business handler | compose_api/authentication.py::get_optional_principal | tests/api/test_authentication.py::test_every_router_rejects_bad_credentials | PASS | — |
| AUTH0-004 | Behavior; errors | Reject wrong scheme, empty/extra/duplicate header | Generic 401 and Bearer challenge | compose_api/authentication.py::_parse_bearer_token | tests/api/test_authentication.py malformed-header and duplicate-header tests | PASS | — |
| AUTH0-005 | Validation 5; acceptance 9–10 | Cryptographic RS256 verification only | Signature verified; HS256 rejected | compose_api/authentication.py::Auth0Verifier.verify | tests/api/test_authentication.py::test_wrong_signing_key_rejected; test_symmetric_algorithm_rejected | PASS | — |
| AUTH0-006 | Validation 7; acceptance 7 | Exact issuer | Different issuer rejected; trailing slash derived once | compose_api/authentication.py::Auth0Verifier.__init__ | tests/api/test_authentication.py::test_invalid_claims_rejected; test_verifier_follows_settings | PASS | — |
| AUTH0-007 | Validation 8; acceptance 8 | Exact audience, including audience arrays | Other API/client audience rejected | compose_api/authentication.py::Auth0Verifier.verify | tests/api/test_authentication.py::test_valid_token_yields_principal; test_invalid_claims_rejected | PASS | — |
| AUTH0-008 | Validation 6; acceptance 6 | Expiration and required claims | exp/iat/iss/aud/sub required; expired rejected | compose_api/authentication.py::Auth0Verifier.verify | tests/api/test_authentication.py::test_invalid_claims_rejected | PASS | — |
| AUTH0-009 | Decision 6 | Clock-skew policy | 60 seconds; future iat and expiration outside leeway rejected | compose_api/authentication.py::JWT_LEEWAY_SECONDS | tests/api/test_authentication.py::test_small_clock_skew_is_tolerated; test_skew_beyond_leeway_is_rejected | PASS | — |
| AUTH0-010 | Validation 3; errors | Malformed JWT and missing kid | Reject without using unverified claims | compose_api/authentication.py::Auth0Verifier.verify | tests/api/test_authentication.py::test_missing_kid_rejected; malformed header cases | PASS | — |
| AUTH0-011 | JWKS; acceptance 11 | Immediate rotation refresh | Unknown kid refreshes once, then rejects if unresolved | compose_api/authentication.py::JwksCache.get_key | tests/api/test_authentication.py::test_rotated_key_is_fetched_immediately; test_each_unknown_kid_refreshes_once_then_is_rejected | PASS | — |
| AUTH0-012 | JWKS; decision 6 | Coalesce concurrent refreshes | Concurrent new-key requests share refresh | compose_api/authentication.py::JwksCache.get_key | tests/api/test_authentication.py::test_concurrent_unknown_kid_requests_share_one_refresh | PASS | — |
| AUTH0-013 | JWKS; acceptance 12 | Cache valid keys | 600-second TTL, no per-request fetch for cached key | compose_api/authentication.py::JwksCache | tests/api/test_authentication.py::test_jwks_is_cached_and_refreshed_on_rotation | PASS | — |
| AUTH0-014 | JWKS; errors | Timeout/network failure | 5-second HTTP timeout; cold cache fails closed | compose_api/authentication.py::JwksCache._refresh | tests/api/test_authentication.py::test_jwks_timeout_fails_closed; test_jwks_outage_fails_closed | PASS | — |
| AUTH0-015 | JWKS; errors | Malformed JWKS document | Sanitized 401 rather than application exception | compose_api/authentication.py::JwksCache._refresh | tests/api/test_authentication.py::test_malformed_jwks_fails_closed (five cases) | PASS | — |
| AUTH0-016 | JWKS key selection | Use eligible signing keys | String kid, RS256, sig or absent use | compose_api/authentication.py::JwksCache._refresh | tests/api/test_authentication.py::test_jwks_only_selects_rs256_signing_keys (three cases) | PASS | — |
| AUTH0-017 | JWKS; decision 6 | Cached keys during outage | Keep known keys; 30-second retry backoff | compose_api/authentication.py::JwksCache | tests/api/test_authentication.py::test_cached_keys_survive_a_jwks_outage; test_expired_cache_backs_off_during_an_outage | PASS | — |
| AUTH0-018 | Principal; acceptance 13–14 | Central immutable minimal principal | No token/raw claims/PII persistence; frozen fields | compose_api/authentication.py::AuthenticatedPrincipal | tests/api/test_authentication.py::test_principal_is_immutable; source inspection | PASS | — |
| AUTH0-019 | Principal | Normalize scopes and permissions | String scope split; only list strings retained | compose_api/authentication.py::_principal_from_claims; _string_set | tests/api/test_authentication.py::test_permissions_claim_is_normalised | PASS | — |
| AUTH0-020 | Non-goals; acceptance 24 | No new authorization or persistence | Roles confer no endpoint access; no schema/ownership changes | routers; git diff origin/main...HEAD | Route tests; branch diff inspection | PASS | — |
| AUTH0-021 | Decision 3; endpoint matrix | Health/version ignore credentials | Always public, including malformed header | compose_api/api/main.py | tests/api/test_authentication.py::test_health_and_version_ignore_credentials | PASS | — |
| AUTH0-022 | Config; acceptance 15 | Use existing settings and override convention | auth0_domain/audience read at use; issuer derived | compose_api/config.py; compose_api/authentication.py::get_auth0_verifier | tests/api/test_authentication.py::test_verifier_follows_settings | PASS | — |
| AUTH0-023 | Config rollout decision | Missing configuration fails safely | Anonymous works; supplied token receives 401 | compose_api/authentication.py::_authenticate | Auth dependency tests; docs/index.md | PASS | — |
| AUTH0-024 | Config; acceptance 22 | Separate production and local audiences | Production api.compose.cam.uchc.edu; local api.compose.local | kustomize/config/compose-api-rke/api.env; overlays/compose-api-local/auth0.env | tests/common/test_deployment_auth0_config.py | PASS | — |
| AUTH0-025 | Deployment phase 5 | Actual ConfigMap sources | Shared RKE API config plus local merge override | kustomize/overlays/compose-api-local/kustomization.yaml | Deployment tests; kustomize render | PASS | — |
| AUTH0-026 | Dependency selection; phase 2 | One maintained JWT implementation | Locked PyJWT crypto with async httpx, no Auth0 Management secret | pyproject.toml; uv.lock; compose_api/authentication.py | make check; Python 3.13 and 3.14 suites | PASS | — |
| AUTH0-027 | OpenAPI; acceptance 19 | Optional bearer schema | BearerAuth plus empty security alternative | compose_api/api/main.py::custom_openapi | tests/api/test_authentication.py::test_openapi_documents_optional_bearer | PASS | — |
| AUTH0-028 | OpenAPI; phase 4 | Checked-in schema generated from application | Regeneration produces no schema diff | compose_api/api/openapi_spec.py | uv run python compose_api/api/openapi_spec.py; git diff --exit-code compose_api/api/spec/ | PASS | — |
| AUTH0-029 | Client; acceptance 25 | Regenerate client, never hand-edit | Official make clients; anonymous Client remains usable | compose_api/api/client; scripts/generate-api-client.sh | LIB_DIR=/tmp/auth0-cross-repo-audit/published-client uv run make clients | PASS | — |
| AUTH0-030 | Backward compatibility | Stable operation IDs and upload wire contract | pbest operations unchanged; File upload types retained | compose_api/api/client; routers | tests/api/test_authentication.py::test_pbest_operations_keep_their_paths; tests/api/test_hpc_run_serialization.py | PASS | — |
| AUTH0-031 | Client compatibility | AuthenticatedClient and Client both work | Header only for authenticated client; documented 404 decoded | compose_api/api/client/api/results/get_simulation_status.py | tests/api/test_authentication.py::test_generated_client_keeps_optional_bearer_and_documented_404 | PASS | — |
| AUTH0-032 | Tests; phase 6 | Deterministic auth suite | RSA signing plus mocked JWKS, no live token fixture | tests/fixtures/auth_fixtures.py; tests/api/test_authentication.py | Final non-SLURM suites on both Python versions | PASS | — |
| AUTH0-033 | Phase 6 | Quality gate | Lock, pre-commit, strict mypy, deptry pass | Makefile; .pre-commit-config.yaml | make check | PASS | — |
| AUTH0-034 | Phase 6; acceptance 18 | Broader regression gate | Docker services and container SLURM exercised | tests/fixtures; .github/workflows/main.yml | make test: 98 passed, 7 cluster-only skips; final affected suite rerun | PASS | — |
| AUTH0-035 | Phase 6 | Python version matrix | 3.13 and 3.14 non-SLURM checks pass | .github/workflows/main.yml | uv run --python 3.13 / default 3.14 pytest tests -m not-slurm | PASS | — |
| AUTH0-036 | Logging; acceptance 16 | No token/key disclosure | Bounded auth errors and challenge; no raw library error | compose_api/authentication.py::get_optional_principal; _unauthorized | tests/api/test_authentication.py::test_real_app_rejects_invalid_tokens_without_leaking_them; secret-pattern scan | PASS | — |
| AUTH0-037 | Documentation; acceptance 20–21 | Document configuration, token flow and port | docs use :8000 active catalog endpoint; setup separate | docs/index.md | make docs-test; source inspection | PASS | — |
| AUTH0-038 | Rollout; acceptance 23 | Incremental rollout | Optional settings; separate overlays; no global disable bypass | docs/index.md; config.py; routers | Settings and route tests | PASS | — |
| AUTH0-039 | Rollout steps 3–6; decision 7 | Current live API token smoke | Valid, expired, wrong-audience and malformed real tokens tested | Historical plan notes are not current runtime evidence | No approved interactive user/token provided | BLOCKED | No deployment or live user mutation performed; historical claims not counted as present verification. |
| AUTH0-040 | Phase 6 | Remote CI and deployment validation | Current remote CI/deployed build verified | Local equivalents run; no commit/push authorized | Remote CI on resulting uncommitted state cannot run | BLOCKED | Local gates are separate from remote CI. |
| AUTH0-041 | Non-goals; future policy | Mandatory routes, ownership and role enforcement in Compose | Excluded explicitly by both plans | All business routers use OptionalPrincipal | Public-route tests | N/A | Do not introduce authorization to satisfy a generic audit scenario. |
| AUTH0-042 | Logging optional metrics | JWKS metrics | Only required if existing metrics mandate it | No applicable mandatory auth metrics integration in plan | Source inspection | N/A | Plan explicitly says optional. |
| ROLES-001 | §1–2, §4.1 | Use existing lowercase tenant user role | No new/renamed role | authentication.py::DEFAULT_ROLE; auth0-pulumi/biosim-platform/roles.py | Compose principal tests; Pulumi Action tests | PASS | — |
| ROLES-002 | §4.1; acceptance 1 | Anonymous has no role | principal is None | compose_api/authentication.py::_authenticate | tests/api/test_authentication.py::test_no_header_is_anonymous | PASS | — |
| ROLES-003 | §4.1; acceptance 2 | Every verified machine/person gets user | Mandatory roles field, user unioned by construction | compose_api/authentication.py::_principal_from_claims | tests/api/test_authentication.py::test_valid_token_yields_principal (person and @clients) | PASS | — |
| ROLES-004 | §4.1; acceptance 3 | Read namespaced roles after verification | https://api.biosimulations.org/roles | authentication.py::ROLES_CLAIM; auth0-pulumi/biosim-platform/actions/biosim_roles.js | tests/api/test_authentication.py::test_roles_claim_adds_to_the_default_role | PASS | — |
| ROLES-005 | §4.1–2 | Preserve roles and exact case | No lowercasing; set union prevents duplication | compose_api/authentication.py::_string_set; _principal_from_claims | tests/api/test_authentication.py roles parameterization; direct implementation inspection | PASS | — |
| ROLES-006 | §4.1–2 | Ignore malformed optional role values | Non-list ignored; non-string list members dropped | compose_api/authentication.py::_string_set | tests/api/test_authentication.py roles parameterization | PASS | — |
| ROLES-007 | §4.1–2 | Keep permissions normalization consistent | Shared string-list helper; malformed values no authorization | compose_api/authentication.py::_string_set | tests/api/test_authentication.py::test_permissions_claim_is_normalised | PASS | — |
| ROLES-008 | §4.2 | Update principal construction and immutability tests | All constructors supply roles | compose_api/authentication.py; tests/api/test_authentication.py | make check; test_principal_is_immutable | PASS | — |
| ROLES-009 | §4.3–5 | Document roles and non-authorization | docs, CLAUDE and original plan describe derived roles | docs/index.md; CLAUDE.md; .github/AUTH0_IMPLEMENTATION_PLAN.md | Source inspection; docs build | PASS | — |
| ROLES-010 | §4.6; acceptance 4 | Roles leave OpenAPI/pbest unchanged | Spec byte-identical; operation IDs stable | api/spec; api/routers | Spec regeneration and pbest operation test | PASS | — |
| ROLES-011 | §5.1 | Inventory current Action/runtime/dependencies/secrets names | Live Action recorded without secret values | auth0-pulumi/biosim-platform/actions.py; live-inventory.json | Read-only Auth0 GET: node22, auth0 4.3.1, four matching secret names | PASS | — |
| ROLES-012 | §5.1 | Inventory trigger bindings | Post-login order and credentials-exchange known | live-inventory.json | Read-only GET: one BioSim Roles post-login binding; zero credentials-exchange bindings | PASS | — |
| ROLES-013 | §5.2 | Dedicated least-privilege client/grant | Action grant exactly update:users | auth0-pulumi/biosim-platform/clients.py; clientGrants.py | Pulumi tests and live grant inventory | PASS | — |
| ROLES-014 | §5.2 | Secret storage | Encrypted config; require_secret; write-only Action inputs | auth0-pulumi/biosim-platform/actions.py; stack YAML | Pulumi tests; no plaintext credential pattern in tracked files | PASS | — |
| ROLES-015 | §5.3 | Assign user on first login | No existing role required | auth0-pulumi/biosim-platform/actions/biosim_roles.js::run | Node test: user without roles; missing authorization | PASS | — |
| ROLES-016 | §5.3 | Admin keeps admin and gains user | Assign lacking default, preserve other roles | auth0-pulumi/biosim-platform/actions/biosim_roles.js::run | Node admin test | PASS | — |
| ROLES-017 | §5.3 | Avoid redundant Management calls | Already-user bypasses assignment | auth0-pulumi/biosim-platform/actions/biosim_roles.js::run | Node existing-user test | PASS | — |
| ROLES-018 | §5.3 | Management failure never rejects login | Catch assignment error; user still in claims | auth0-pulumi/biosim-platform/actions/biosim_roles.js::run | Node failure test (mocked Management API) | PASS | — |
| ROLES-019 | §5.3 | First token contains user; sorted claims | Set access and ID token role claims immediately | auth0-pulumi/biosim-platform/actions/biosim_roles.js::run | Node first-login/admin tests | PASS | — |
| ROLES-020 | §5.3 | Email claim conditional | Set namespaced access-token email only when present | auth0-pulumi/biosim-platform/actions/biosim_roles.js::run | Node email/no-email test | PASS | — |
| ROLES-021 | §5.3 | Valid exported handler signature | async function exported | auth0-pulumi/biosim-platform/actions/biosim_roles.js::onExecutePostLogin | Node exported signature test; deployed source equality | PASS | — |
| ROLES-022 | §5.4 | Adopt existing Action, no duplicate | One managed ID equals bound live Action | auth0-pulumi/biosim-platform/actions.py; live-inventory.json | Read-only inventory; preview --refresh (no Action create/replace) | PASS | — |
| ROLES-023 | §5.4 | Singular protected trigger binding | Does not own whole trigger list | auth0-pulumi/biosim-platform/actions.py | Pulumi Action-binding tests; live single binding | PASS | — |
| ROLES-024 | §5.4 | Exact compatible SDK/runtime | 4.3.1 v4 assignRoles syntax on node22 | auth0-pulumi/biosim-platform/actions.py; actions/biosim_roles.js | Live dependency metadata; Node and Pulumi tests | PASS | — |
| ROLES-025 | §5.5 | Offline infrastructure tests and dependencies | Mock config, pytest dev dependency, CI wired | auth0-pulumi/biosim-platform/tests; pyproject.toml; .github/workflows/mypy-check.yml | 14 biosim tests; 4 Compose stack tests; mypy all three stacks | PASS | — |
| ROLES-026 | §5.7 | README describes managed Action and role assignment | Source structure/role ownership documented | auth0-pulumi/biosim-platform/README.md | Source inspection | PASS | — |
| ROLES-027 | §6.1 | Export stable SPA client id | biosim_spa_client_id from owned SPA | auth0-pulumi/biosim-platform/__main__.py | StackReference preview and live client-id comparison | PASS | — |
| ROLES-028 | §6.2 | Production-only user-delegated grant | SPA subject_type user, empty scopes, prod audience | auth0-pulumi/compose-api/clientGrants.py | 4 mocked tests; live grant and refresh preview (7 unchanged) | PASS | — |
| ROLES-029 | §6.2 | Require stack output and same organization | No duplicate SPA resource, missing output fails loudly | auth0-pulumi/compose-api/clientGrants.py | StackReference mocked test; live preview | PASS | — |
| ROLES-030 | §6.2; §7 | Document apply ordering and test command | BioSim output before Compose grant | Both Pulumi READMEs | Source inspection; previews resolved reference | PASS | — |
| ROLES-031 | §5.1 historical adoption | Compare pre-adoption dashboard behavior | Prove no historical behavior lost | Git history records inventory and secret-name correction | Original dashboard export no longer retained | BLOCKED | Current deployed source equality does not recreate historical dashboard evidence. |
| ROLES-032 | §5.6; acceptance 6–7 | Live first-login/admin assignment | Actual first token and persisted user role proven | Offline Action tests pass | No real users created/deleted; no interactive credentials provided | BLOCKED | User expressly forbids creating/deleting users to prove signup. |
| ROLES-033 | §5.7 conditional retirement | Retire old credentials if unused | Identify all old-client consumers before narrowing | Platform locally uses BioSim Management API M2M | Local settings client-id matches live grant | N/A | Old client is not Action-only; do not remove its grant. Excess privileges remain a finding. |
| ROLES-034 | §5.7 | Remove temporary dashboard source | No dashboard export in repository | No actions/biosim_roles.dashboard.js present | Tracked/untracked inventory | PASS | — |
| ROLES-035 | §6.3 | Add Compose-specific frontend request/token flow | Conditional on real Compose feature/call site | rg finds no Compose call in platform/frontend | Direct source search | N/A | Explicitly deferred by current plan; not counted as successful end-to-end integration. |
| ROLES-036 | §6.4; final conditional acceptance | Real person Compose token | After §6.3, verify subject/audience/roles and API request | No Compose frontend request exists | No real person Compose token minted | N/A | Explicit after-§6.3 condition has not been met. |
| ROLES-037 | §4.6; §5 deployment commands; §7 | Commit/apply instructions | User prohibits commits, pushes and infrastructure apply | All changes remain local | Git HEADs unchanged | N/A | Current user instruction supersedes plan commit/up commands. |
| ROLES-038 | §5.2 client grant types live | Action client credentials-only live | Declared grant_types matches live | Pulumi declares client_credentials; live refresh adds refresh_token | Refreshed preview plans removal | BLOCKED | Source is correct; live drift cannot be applied under task authorization. |

Ledger totals: PASS=69, FAIL=0, BLOCKED=5, N/A=6. No claim of 100% completion.

## 4. Cross-repository Auth0 contract

| Contract | compose-api | auth0-pulumi | Platform | Result/evidence |
|---|---|---|---|---|
| Tenant/domain | AUTH0_DOMAIN | biosim-platform ESC config; Compose shares it | NUXT_PUBLIC_AUTH0_DOMAIN / AUTH0_DOMAIN | Same dev-bu7yo7484tyxu6a1.us.auth0.com; live provider config and checked-in GKE/RKE agree |
| Issuer | Derived HTTPS domain + trailing slash | Tenant-issued tokens | Derived/configured issuer; optional trusted-issuer map | Single configured tenant agrees; local extra issuer map absent |
| Production audience | https://api.compose.cam.uchc.edu | Compose production ResourceServer | BioSim audience https://api.biosimulations.org | Deliberately different; a BioSim token MUST fail at Compose |
| Local audience | https://api.compose.local | Separate local ResourceServer | No local Compose token acquisition | Compose local M2M grant verified; SPA production-only |
| SPA client | Not required for inbound JWT verification | biosim_spa_client_id output | GA9L0b7xoDELHoHPfpdx4SSgo8S1fAkP | Exact match in live SPA, GKE/RKE config and stack reference |
| Client type/flow | M2M and person access tokens accepted | SPA authorization_code/refresh_token; test client client_credentials | auth0-vue, PKCE flow delegated to SDK | Static/mock verified; no interactive login completed |
| GKE callback/logout | N/A | https://biosim.biosimulations.org | window.location.origin | Matches source and live SPA |
| RKE callback/logout | N/A | Added https://biosim.cam.uchc.edu locally | RKE uses that origin with same SPA client | Source fix tested; live allowlist still missing it |
| Native local callback/logout | N/A | README explicitly excludes localhost; source does too | .env.example uses localhost:4200 and production SPA id | Unresolved policy conflict; live callback/logout currently permit 4200, web origin does not |
| RKE frontend-dev | N/A | No matching dedicated client/origin | biosim-dev.cam.uchc.edu overlay lacks Auth0 variables | Not a verified login environment; must supply intended client/URLs before auth use |
| Kubernetes local frontend | N/A | No biosim-local client/origin | Legacy BASE_URL/API_URL config, no Auth0 variables | Not a verified runtime-configured login environment |
| Web/CORS origins | Compose allows its own host and local development hosts | SPA web/allowed origins GKE + new RKE source | Platform CORS separate from Auth0 | Compose does not yet allow production Platform browser origins; deferred feature must add CORS with its token path |
| API base URLs | https://compose.cam.uchc.edu | Audience is an identifier, not endpoint URL | GKE api.biosim.biosimulations.org; RKE api.biosim.cam.uchc.edu | Distinct API URL and audience intentional |
| Requested scopes | No scope required | Compose grants [] | SDK defaults openid profile email; useRefreshTokens adds offline_access | Installed SDK source inspected; plugin test pins BioSim audience |
| Permissions/RBAC | Extracted, not enforced | Compose RBAC off; BioSim enforce_policies true/access_token_authz | Roles and permissions checked separately, exact matching | Backend tests verify fail-closed role/permission gates; role alone never implies permission |
| Roles | Derived user + namespaced claim | Tenant user/admin/publisher; Action assigns user | Same role names/claim | Matching source; deployed Action equals repository source |
| Role-permission mapping | No mapping | Not managed in these stacks | Authorization helpers consume claims/scope independently | No Compose mapping required; full live BioSim role-permission policy not proven by these stacks |
| Claims | https://api.biosimulations.org/roles | Access + ID token roles; access-token email | Same roles/email namespaces | Matches; Action does not stamp email_verified/auth_time, so optional Platform policies cannot assume them |
| Signing algorithm | RS256 allowlist | All relevant APIs RS256 | RS256 verification | Signed-RSA mock tests; live API metadata matches |
| JWKS | Async HTTP, 600s TTL, unknown-kid refresh, 5s timeout, 24h maximum stale age | Tenant JWKS | Separate per-issuer cache with bounded stale age/backoff | Both tested; prolonged outage fails closed after the explicit stale bound |
| Token lifetime | exp required, 60s leeway | 86400 API / 7200 web seconds | exp required; bounded claim checks | No conflation of issued lifetime and session lifetime |
| Refresh/session | No browser session | BioSim live allow_offline_access true, now explicit in source | useRefreshTokens true, localstorage | Source/live requirement aligned; interactive renewal not tested |
| IdP-initiated login | N/A | Live initiate_login_uri preserved explicitly | /login client-only route | Source fix prevents preview from removing existing live login URI |
| Post-login Action | Reads verified roles | Singular protected binding, node22, auth0 4.3.1 | Roles originate from Action | One live binding; no credentials-exchange binding; offline behavior tests pass |
| Action Management grant | Not used | Dedicated Action client: update:users only | Separate backend client | Live grant matches; Action client itself has drifted refresh_token grant type |
| Backend Management grant | Not used | Existing backend grant remains outside declared clientGrants.py | Configured locally to e3wDHGNMdIaFU7jOoeNlzXtqjB8L8MA0 | Live grant lacks delete:users; extra client/role administration scopes present; no blind narrowing/import performed |
| User-delegated Compose grant | Valid person token accepted | Production-only subject_type=user, scopes=[] | No Compose call sites yet | Live grant verified, full browser→Compose path explicitly deferred |
| Bearer attachment | Invalid supplied token is always 401 | No token-routing behavior | Now only configured Platform origin/path gets automatic BioSim bearer token | Fixed; actual plugin and destination tests pass |
| Secrets/environment | Public domain/audience only | ESC and encrypted rolesActionClientSecret | Backend Management secret is server-only | Credential pattern scan found none in tracked/untracked source; values not printed |
| Resource ownership/order | Application only | BioSim owns tenant/SPA/roles/Action; Compose references SPA | Consumes non-secret IDs | No duplicate Action/SPA creation in previews; apply BioSim output before Compose grant |

Source anchors: `compose_api/authentication.py` (`Auth0Verifier`, `JwksCache`, `_parse_bearer_token`); `auth0-pulumi/biosim-platform/{clients,resourceServers,actions,clientGrants,roles}.py`; `auth0-pulumi/compose-api/clientGrants.py`; `platform/frontend/app/plugins/auth0.client.ts`; `platform/frontend/app/utils/api-auth.ts`; `platform/backend/biosim_server/common/auth/{auth0,roles}.py`; per-environment ConfigMaps.

## 5. Authentication / authorization regression results

| Scenario | Evidence tier | Result |
|---|---|---|
| Anonymous Compose API/catalog/probes | ASGI + Docker database integration | Pass; no auth requirement added |
| Missing token on Platform protected profile route | ASGI signed-token suite | 401 |
| Valid person and M2M token | RSA/JWKS unit + ASGI integration | Principal accepted; Compose user role derived |
| Malformed header/token, invalid signature, issuer/audience, expired token | RSA/JWKS + real FastAPI dependencies | Rejected; no anonymous downgrade; sanitized errors |
| Unknown kid / rotation / timeout / malformed JWKS | Transport-mocked integration | Rotation refresh succeeds; unresolved/cold failures rejected; malformed response regression fixed |
| Malformed roles/permissions | Unit and ASGI tests | Compose malformed entries ignored; Platform permission/role checks deny absent grants |
| Required/absent roles and permissions | Platform backend tests | Exact AND/OR helper semantics, fail-closed empty requirements |
| Ownership/profile tenant boundary | Platform tests/users and auth suite | Foreign issuer cannot access configured tenant Management operations; legacy ownership tested |
| Sign-up initiation | Static source only | loginWithRedirect(screen_hint=signup); no real user creation |
| Sign-in initiation | Static source and SDK inspection | Login redirect uses configured client/domain/audience; live GKE URL allowed |
| Callback/session restoration | Static installed SDK + configuration | SDK handles code/state then restores appState target; no complete browser OAuth exchange run |
| Token acquisition/scopes | Actual plugin test with SDK boundary mocked | BioSim audience passed; SDK source provides OIDC scopes; not a real tenant-issued user token |
| Bearer destination | Four Node tests, including actual plugin | Correct origin/path only; external/Compose/Auth0 requests get no automatic Platform token |
| Logout | Static source + live allowlist inventory | origin returnTo; GKE agrees, RKE pending apply, local policy unresolved |
| Live roles on first login/admin | Offline Action tests only | Not end-to-end tested; current deployed source confirmed identical |
| Browser→Compose person token | Explicitly deferred | No call site; cannot report end-to-end success |

Platform's existing Management/profile changes were inspected and its signed-JWT tests run. Its current local configuration has no extra trusted issuers. Ownership storage still uses subject-only keys: enabling unrelated trusted issuers requires a separate ownership migration/review; this audit does not claim that configuration is safe for arbitrary issuers.

## 6. Findings (unresolved first)

| Severity | Finding / expected vs actual | Root cause / impact | Disposition and evidence |
|---|---|---|---|
| BLOCKER | All-environment sign-in cannot be declared working | RKE origin absent live; local template uses shared SPA but Pulumi intentionally excludes localhost; dev/local cluster overlays have no Auth0 client values | RKE source corrected; no live apply permitted. `biosim-platform/clients.py`, Platform ConfigMaps, live inventory and refreshed preview |
| HIGH | Platform delete-account needs delete:users; configured Management client lacks it | GET/PATCH/ticket scopes exist, delete scope does not; deletion would fail at provider and map to backend 502 | Not mutated. `users/router.py::delete_me`, `auth0_management.py::delete_auth0_user`, local client-id comparison and live grant inventory. No actual account deleted |
| HIGH | Broader Management grant is not least privilege / not owned by current grant module | Existing grant includes client/role administration permissions beyond backend profile functions | Ownership/other consumers must be established before importing/narrowing. Do not confuse this client with the correctly scoped dedicated Action client |
| BLOCKER | First-login/admin and browser session flow unproven | Live read-only configuration and mocks cannot establish successful interactive login | No supplied authorized user session; no signup/user mutation allowed. Roles live acceptance remains BLOCKED |
| MEDIUM | Tenant drift persists | Live Action client has refresh_token; localhost callback/logout additions differ from source | `pulumi preview --refresh`: two resource updates planned (SPA, Action client). No apply. Exact URL policy must be settled before reconciling |
| MEDIUM — fixed locally | Compose stale-key outage policy had no absolute expiration | Known signing keys could remain accepted through repeated JWKS failures | Added 24-hour maximum stale age and regression test; prolonged outage now fails closed |
| LOW | Tracked branch artifact .DS_Store | Already present in Compose branch relative to origin/main | Not created or deleted by audit; review/remove separately before publication |
| HIGH — fixed locally | Platform sent BioSim bearer to unrelated hosts | Global interceptor ignored destination | Destination helper + actual-plugin tests; includes Auth0, legacy, Compose, lookalike hosts and path boundaries |
| MEDIUM — fixed | Malformed JWKS array/string produced 500 | PyJWKSet assumes a mapping; cache accepted unusable key metadata | Explicit document validation and RS256 signing-key selection; eight focused cases |
| MEDIUM — fixed locally | RKE callback/logout/web origins absent | Shared SPA provisioned for GKE only | Added exact deployed RKE origin; mocked Pulumi assertion; refreshed preview |
| MEDIUM — fixed locally | Reconciliation would remove live IdP login URI; refresh requirement implicit | SPA/resource-server fields omitted | Preserve initiate_login_uri and explicitly enable existing BioSim offline access; Pulumi tests |
| LOW — fixed | Generated client lagged documented 404 response behavior | Spec regenerated earlier without matching client regeneration | Official make clients; no hand-edits; Client/AuthenticatedClient and HpcRun checks |
| VALIDATION — fixed | 30 Platform suite setup errors | mongo:latest refuses Linux >=6.19 (container itself reported SERVER-121912) | Pinned fixture mongo:7, matching Compose; full affected suite now 960 passed |

No claim that the localhost policy should automatically be widened: the current Pulumi README explicitly records removal as security remediation, while Platform's current .env.example and live callbacks rely on localhost. This is a real conflicting policy, not a code change that can safely be guessed.

## 7. Changes made

| Repository/files | Why / behavior | Verification |
|---|---|---|
| Compose `compose_api/authentication.py` | Fail closed on non-object JWKS; retain only string-kid RS256 signing keys; cap stale-key use at 24h | Malformed-JWKS, key-selection and prolonged-outage tests; full affected tests |
| Compose `tests/api/test_authentication.py` | Add error-path coverage; real @clients subject; generated-client bearer/404 test | Both Python versions; make check |
| Compose generated client files listed below | Official generator updates documented 404 handlers; remaining changes are generator whitespace | HpcRun wire test; anonymous/authenticated generated client test; spec unchanged |
| Compose `AUTH0_CROSS_REPOSITORY_AUDIT.md` | Complete ledger, contracts, evidence and blockers | Ledger/status and diff checks |
| Pulumi `biosim-platform/clients.py` | Add exact RKE origin to four allowlists; preserve live IdP login URI | Mocked tests + refreshed non-destructive preview |
| Pulumi `biosim-platform/resourceServers.py` | Explicit existing BioSim allow_offline_access for SPA refresh flow | Mocked session configuration test; live inventory |
| Pulumi `biosim-platform/tests/test_program_structure.py` | Pin GKE/RKE URL sets and session/IdP contract | 14 offline tests |
| Pulumi `biosim-platform/README.md` | Document both deployed frontend origins | Diff inspection |
| Platform `frontend/app/plugins/auth0.client.ts` | Gate automatic credentials/bearer by configured API destination | Actual plugin executed in Node harness |
| Platform `frontend/app/utils/api-auth.ts` | Resolve request/baseURL securely and match origin/path | Destination/path/lookalike/relative/Request tests |
| Platform `frontend/tests/api-auth.test.mjs` | Four regression tests; actual plugin plus URL cases | npm run test:auth |
| Platform `frontend/package.json`, `.github/workflows/frontend-ci.yaml` | Run auth tests locally and in CI without new dependency | npm auth/lint/typecheck/build |
| Platform `backend/tests/fixtures/database_fixtures.py` | Pin Mongo 7 to restore deterministic DB tests on available kernel | 960-pass backend suite; Ruff/mypy |

Pre-existing Compose roles-plan and .gitignore edits are unchanged. All 31 existing Platform tracked edits and nine original untracked files are preserved. No lockfiles or runtime dependency declarations changed; package.json adds only a test script.

## 8. Verification commands

| Repository | Command | Purpose | Result |
|---|---|---|---|
| compose-api | `make check` | Lock, pre-commit/Ruff, strict mypy, deptry | PASS |
| compose-api | `uv run python -m pytest tests -m 'not slurm' -q` | Broad Docker-backed non-SLURM regression | 95 passed, 21 deselected |
| compose-api | `UV_PROJECT_ENVIRONMENT=... uv run --python 3.13 python -m pytest tests -m 'not slurm' -q` | Python 3.13 matrix | 95 passed, 21 deselected |
| compose-api | `uv run python -m pytest tests/api/test_authentication.py ... -q` | Final auth/client/deployment focus | 67 passed |
| compose-api | `make docs-test` | MkDocs validation | PASS |
| compose-api | `uv run python compose_api/api/openapi_spec.py`; `git diff --exit-code compose_api/api/spec/` | Schema regeneration | PASS; no spec diff |
| compose-api | `LIB_DIR=/tmp/... uv run make clients` | Official generated-client regeneration | PASS; no hand-edit |
| auth0-pulumi | `uv run --directory biosim-platform python -m pytest tests -m 'not live' -q` | Offline Pulumi/Action tests | 14 passed, 9 deselected |
| auth0-pulumi | `MYPYPATH=biosim-platform uv run mypy biosim-platform` | Pulumi strict typing | PASS |
| auth0-pulumi | `uv run --directory compose-api python -m pytest tests -q` | Compose Pulumi grant tests | 4 passed |
| auth0-pulumi | `node --test biosim-platform/actions/` | Deployed Action behavior/signature | 7 passed |
| auth0-pulumi | `pulumi preview --refresh --non-interactive --diff` | Non-destructive live drift check | PASS to run; 2 updates remain planned, unapplied |
| platform/backend | `uv run pytest -m 'not integration' -q` | Backend regression with Docker | 960 passed, 15 skipped, 8 deselected |
| platform/backend | `uv run ruff check .`; `uv run mypy biosim_server tests` | Backend quality gates | PASS |
| platform/frontend | `npm run lint`; `npm run typecheck`; `npm run build` | Frontend quality/build | PASS |
| platform/frontend | `npm run test:auth` | Token destination/plugin regression | 4 passed |
| all three | `git diff --check` | Whitespace/error scan | PASS |
| compose-api | `coderabbit review --agent --uncommitted --include-untracked --dir .` | External review attempt | Started analysis but was interrupted; no completed finding set, therefore not evidence of cleanliness |

## 9. Remaining limitations

Live Auth0 management metadata was readable with existing local Pulumi credentials, but no interactive browser session or real user token was used. Signup, sign-in callback exchange, session renewal, first-login role assignment and admin role persistence therefore remain blocked. No test user was created or deleted, per the task boundary.

The RKE allowlist correction and Action-client grant cleanup are source changes only; applying Pulumi was expressly prohibited. The refreshed preview identifies two updates, so the Pulumi stacks are not no-op clean against the tenant. The Platform backend’s account-deletion path needs `delete:users`, while the configured client also has broader existing administration scopes; changing those grants requires an ownership decision and a separate controlled infrastructure change.

The frontend has no Compose API call site. Its new interceptor guard prevents sending the BioSim token to Compose/Auth0/legacy hosts, but it does not prove a person can obtain a Compose audience token or call Compose end to end. The Compose API keeps a 24-hour stale-key window during JWKS outages; this is bounded and fail-closed after the bound, but a revoked key can remain usable during that interval.

## 10. Final Git / push review

| Repository | Branch / HEAD | Final state | Diff check | Push blocker |
|---|---|---|---|---|
| compose-api | `feature/auth0-implementation` / `ebb28c7` | Original plan and `.gitignore` edits plus this audit, auth hardening/tests, generated-client updates and docs; no staged changes | PASS | Live and cross-repo gates above |
| auth0-pulumi | `feature/compose-api-user-access` / `429c246` | Original clean tree now has only audit-originated SPA URL/session/grant tests/docs/source edits; no staged changes | PASS | Unapplied RKE/URL and client-grant drift |
| platform | `chore/api-improvements` / `0d40820` | Original 31 tracked + 9 untracked working-tree edits preserved; audit adds frontend token-destination guard/tests, package test script/CI hook, Mongo 7 fixture pin | PASS | Existing user/session live flow not exercised; all unrelated work remains dirty |

No commit, push, `pulumi up`, `pulumi destroy`, deployment, or live-user mutation was performed. The smallest set of actions before push is: decide and apply the intended callback/logout policy for GKE/RKE/local; reconcile the two Pulumi updates and Action-client grant drift; grant or redesign the Platform account-deletion Management permission; then run an authorized browser/user smoke test and rerun the refreshed previews and final gates.

## 11. Second, independent audit pass (2026-09-25)

Every earlier claim was re-checked by executing it, not by reading this report. Two results change the verdict.

**New finding: CRITICAL, live regression, fixed in source only.** The Pulumi-managed BioSim Roles Action (deployed with
Part 2) does not stamp `https://api.biosimulations.org/email_verified`. `platform/auth0/actions/post-login.js`, the
Action it replaced (same four secret names), stamped it on every access token. The Platform backend treats a missing
claim as unverified (`biosim_server/common/auth/auth0.py`, where only `True` counts). That disables the verified-email
ownership fallback (`common/auth/roles.py::is_owner`) and the legacy "my runs" email match
(`simulations/router.py`). Owners of legacy runs without an `owner_sub` lose access. The dashboard inventory in §5.1
of the roles plan missed it. Fixed in `auth0-pulumi/biosim-platform/actions/biosim_roles.js`, with a Node test
(which fails against the deployed code) and a Pulumi test assertion. **Not applied** (task prohibits `pulumi up`).
A targeted apply (`--target …::auth0:index/action:Action::biosim_roles_action`) previews as exactly 1 update and
13 unchanged.

**Verified independently:**
- compose-api: `make check`; 96 non-SLURM and 14 SLURM tests pass (7 are `cluster_only` skips).
- compose-api: the spec regenerates with no diff, and the working-tree client equals fresh generator output
  byte for byte (not hand-edited).
- auth0-pulumi: mypy on all three stacks; 14 + 4 offline tests; 8 Action tests.
- Refresh preview: compose-api has 7 unchanged (no drift). biosim-platform shows live SPA drift: `localhost` is live,
  and the RKE origin is missing live, so **RKE sign-in currently fails**.
- platform: 960 back-end tests pass; ruff clean; mypy clean on 173 files. The front end passes `test:auth` (4),
  lint, typecheck and build.
- No whitespace errors; the credential-pattern scan finds nothing in any repo.
- The token-destination guard causes no regression. The legacy `DELETE /runs/{id}` needs a token from another tenant
  (`auth.biosimulations.org`, scope `delete:SimulationRuns`) and could never have accepted the Platform token.
- The dedicated Action client is correctly scoped. Auth0 documents `POST /users/{id}/roles` as needing any one of
  `update:users` or `create:role_members`.

**Still open:**
- The `localhost` callback policy conflict blocks applying the SPA change.
- `.DS_Store` is committed on the compose-api branch (`e2afd01`).
- `.gitignore` ignores `.agents/` while the roles plan inside it is tracked.
- Live first-login and person-token checks.
- Compose `APP_ORIGINS` lacks the Platform origins (a prerequisite for §6.3, recorded in the roles plan).
