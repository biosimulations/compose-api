# Auth0 Roles: Implementation Plan

| | |
|---|---|
| **Status** | Ready to implement. Part 1 was verified against the code, Part 2 offline; Part 3 is design only (see [Verification status](#verification-status)) |
| **Date** | 2026-09-24 |
| **Repos** | `compose-api` (this repo) · `~/Github/UCHC/auth0-pulumi` (`biosim-platform/` and `compose-api/` stacks) |
| **Tenant** | `dev-bu7yo7484tyxu6a1.us.auth0.com` (shared by BioSim Platform and compose-api) |
| **Builds on** | `.github/AUTH0_IMPLEMENTATION_PLAN.md` (optional Auth0 bearer authentication, complete) |

## 1. Goal

> Authenticated callers automatically hold the role **`user`**. Anonymous callers hold no role and can still use the
> API.

| Caller | Principal in compose-api | Roles |
|---|---|---|
| No `Authorization` header | `None` | none (anonymous) |
| Machine token (client credentials) | `AuthenticatedPrincipal` | `{"user"}` |
| Logged-in person's token (only after Part 3) | `AuthenticatedPrincipal` | `{"user"}` ∪ their Auth0 roles, e.g. `{"user", "admin"}` |
| Invalid token | none: 401, unchanged | n/a |

**Roles identify, they don't authorize.** This plan makes roles *available* to handlers. No endpoint checks a role,
and every endpoint stays open to anonymous callers. Gating an endpoint on a role is a separate, later decision that
builds on `principal.roles`.

## 2. Settled decisions

1. **The role is the existing tenant role `user`** (lowercase). It's declared in
   `auth0-pulumi/biosim-platform/roles.py` as `biosim_user_role` ("Default role for all authenticated platform
   users") and shared with BioSim. There's no compose-api-specific role, no `User` role, and no rename.
2. **compose-api derives `user` itself** for every verified token. Machine tokens can never carry an Auth0 user role,
   so this is the only way "authenticated means `user`" can hold for them.
3. **compose-api also reads the roles claim** `https://api.biosimulations.org/roles` that the tenant's
   `BioSim Roles` Action writes, so a person's other roles (`admin`, `publisher`) come through as well.
4. **`BioSim Roles` moves into Pulumi** (`biosim-platform` stack, which owns the role). This makes the role it assigns
   reviewable, lets it assign `user` explicitly, and makes a Management API failure unable to block a login.
5. **Part 3 (people calling compose-api as themselves) is conditional** on a product decision (§6.0).

**Non-goals:** enforcing roles on endpoints; RBAC permissions on the Compose-API API (it stays off); new roles;
changes to anonymous access, the OpenAPI contract, or pbest.

## 3. Current state (why this is needed)

| Finding | Evidence |
|---|---|
| compose-api drops roles: `AuthenticatedPrincipal` has no `roles` field | `compose_api/authentication.py` |
| Every authenticated compose-api caller today is a machine (`sub = <client_id>@clients`); no app has user-delegated access to Compose-API | Dashboard audit 2026-09-24, check 11 |
| Machine tokens never carry roles: post-login Actions don't run for client credentials, and clients can't hold tenant roles | Auth0 behaviour |
| The only role assignment is the dashboard-only post-login Action `BioSim Roles`: "if a user has no roles, assigns a default role via the Management API; adds `…/roles` (access and ID token) and `…/email` (access token) claims" | Dashboard audit, check 19 |
| That Action **isn't in Pulumi**, and it doesn't catch errors from its Management API call, so a failure there can fail a login | Audit "Anything surprising"; `grep` of `auth0-pulumi` |
| Its behaviour differs from the goal: it assigns *a* default role only to users with **no** roles; an `admin` without `user` never gets `user` | Audit, check 19 |
| Role assignments and role permissions aren't modelled in Pulumi | `biosim-platform/README.md`, *Roles* |

---

## 4. Part 1: compose-api derives the `user` role (do this first)

This part is independent: it needs no Auth0 change and delivers the goal for every caller that exists today.
**Verified:** applied to a clean export of `HEAD` (`7ef746c`). `pre-commit` and `mypy --strict` (91 files) are clean,
the auth tests pass (54 passed; the one Docker-dependent test couldn't run because the daemon was down), and the
OpenAPI spec is **byte-for-byte unchanged**. Removing the default role makes 6 of the new and updated tests fail.

### 4.1 `compose_api/authentication.py`

```diff
@@ -33,6 +33,13 @@ JWKS_TIMEOUT_SECONDS = 5.0
 # (TokenVerifier) defaults to the same 60 s.
 JWT_LEEWAY_SECONDS = 60

+# Every verified caller holds DEFAULT_ROLE; an anonymous caller has no principal and so no role. It is the tenant-wide
+# Auth0 role "user" owned by auth0-pulumi/biosim-platform (roles.py: biosim_user_role) -- keep the spelling in step.
+DEFAULT_ROLE = "user"
+# Namespaced claim in which the tenant's "BioSim Roles" post-login Action lists the caller's Auth0 role names. Only
+# tokens issued to a logged-in user carry it; client-credentials (M2M) tokens never do.
+ROLES_CLAIM = "https://api.biosimulations.org/roles"
+

 @dataclass(frozen=True, slots=True)
 class AuthenticatedPrincipal:
@@ -41,6 +48,7 @@ class AuthenticatedPrincipal:
     audience: tuple[str, ...]
     scopes: frozenset[str]
     permissions: frozenset[str]
+    roles: frozenset[str]  # always contains DEFAULT_ROLE; roles identify the caller, they do not authorize anything yet


 class AuthenticationError(Exception):
@@ -165,18 +173,21 @@ def _principal_from_claims(claims: dict[str, Any]) -> AuthenticatedPrincipal:
         raise AuthenticationError("missing_claim")
     audience = claims["aud"]
     scope = claims.get("scope")
-    permissions = claims.get("permissions")
     return AuthenticatedPrincipal(
         subject=subject,
         issuer=claims["iss"],
         audience=(audience,) if isinstance(audience, str) else tuple(audience),
         scopes=frozenset(scope.split()) if isinstance(scope, str) else frozenset(),
-        permissions=frozenset(p for p in permissions if isinstance(p, str))
-        if isinstance(permissions, list)
-        else frozenset(),
+        permissions=_string_set(claims.get("permissions")),
+        roles=frozenset({DEFAULT_ROLE}) | _string_set(claims.get(ROLES_CLAIM)),
     )


+def _string_set(value: object) -> frozenset[str]:
+    """The strings in a list-valued claim; anything else (absent, a bare string, a number) contributes nothing."""
+    return frozenset(item for item in value if isinstance(item, str)) if isinstance(value, list) else frozenset()
+
+
 @lru_cache(maxsize=4)
 def _build_verifier(domain: str, audience: str) -> Auth0Verifier:
     return Auth0Verifier(domain=domain, audience=audience)
```

Design notes:
- **`roles` has no default and isn't optional.** Every principal is built by `_principal_from_claims`, which always
  includes `DEFAULT_ROLE`. So "authenticated means `user`" holds by construction, and a missing role can't be
  mistaken for anonymous (anonymous is `principal is None`).
- **The claim is trusted** because it sits inside a token whose signature, issuer, audience and expiry were just
  verified. Anything other than a list of strings is ignored, never an error. A malformed optional claim mustn't
  turn a valid token into a 401.
- **Case is kept as-is.** Auth0 role names are case-sensitive, and the tenant's are lowercase.
- `_string_set` also replaces the inline `permissions` parsing, since the rule is the same for both claims.
- Adding a field to the frozen dataclass changes its **positional** constructor. There are only two call sites, both
  in tests, updated below.

### 4.2 `tests/api/test_authentication.py`

```diff
@@ -15,7 +15,9 @@ from httpx import ASGITransport

 from compose_api.api.main import app
 from compose_api.authentication import (
+    DEFAULT_ROLE,
     JWT_LEEWAY_SECONDS,
+    ROLES_CLAIM,
     Auth0Verifier,
     AuthenticatedPrincipal,
     AuthenticationError,
@@ -41,6 +43,7 @@ async def test_valid_token_yields_principal(fake_auth0: FakeAuth0, auth0_verifie
     assert AUTH0_TEST_AUDIENCE in principal.audience
     assert principal.scopes == {"openid", "profile"}
     assert principal.permissions == frozenset()
+    assert principal.roles == {DEFAULT_ROLE}  # an M2M token carries no roles claim, yet still gets the default role


 @pytest.mark.asyncio
@@ -207,6 +210,26 @@ async def test_skew_beyond_leeway_is_rejected(
         await auth0_verifier.verify(fake_auth0.token(**claim_overrides))


+@pytest.mark.asyncio
+@pytest.mark.parametrize(
+    ("roles_claim", "expected"),
+    [
+        (["admin", "publisher"], {"user", "admin", "publisher"}),
+        (["user"], {"user"}),
+        (["admin", 7, None, {"x": 1}], {"user", "admin"}),
+        ("admin", {"user"}),
+        ([], {"user"}),
+    ],
+    ids=["extra-roles", "user-listed-again", "non-strings-dropped", "not-a-list", "empty"],
+)
+async def test_roles_claim_adds_to_the_default_role(
+    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier, roles_claim: object, expected: set[str]
+) -> None:
+    claim: dict[str, Any] = {ROLES_CLAIM: roles_claim}  # a URL is not a valid keyword, so pass it via a dict
+    principal = await auth0_verifier.verify(fake_auth0.token(**claim))
+    assert principal.roles == expected
+
+
 @pytest.mark.asyncio
 async def test_missing_kid_rejected(fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier) -> None:
     token = jwt.encode({"sub": "x"}, fake_auth0.keys["key-1"], algorithm="RS256")
@@ -241,8 +264,11 @@ async def principal_client(auth0_verifier: Auth0Verifier) -> AsyncGenerator[http
     probe = FastAPI()

     @probe.get("/whoami")
-    async def whoami(principal: OptionalPrincipal) -> dict[str, str | None]:
-        return {"subject": principal.subject if principal else None}
+    async def whoami(principal: OptionalPrincipal) -> dict[str, str | list[str] | None]:
+        return {
+            "subject": principal.subject if principal else None,
+            "roles": sorted(principal.roles) if principal else None,
+        }

     probe.dependency_overrides[get_auth0_verifier] = lambda: auth0_verifier
     async with httpx.AsyncClient(transport=ASGITransport(app=probe), base_url="http://testserver") as client:
@@ -253,14 +279,14 @@ async def principal_client(auth0_verifier: Auth0Verifier) -> AsyncGenerator[http
 async def test_no_header_is_anonymous(principal_client: httpx.AsyncClient) -> None:
     response = await principal_client.get("/whoami")
     assert response.status_code == 200
-    assert response.json() == {"subject": None}
+    assert response.json() == {"subject": None, "roles": None}  # anonymous: no role


 @pytest.mark.asyncio
 async def test_valid_token_reaches_handler(principal_client: httpx.AsyncClient, fake_auth0: FakeAuth0) -> None:
     response = await principal_client.get("/whoami", headers={"Authorization": f"Bearer {fake_auth0.token()}"})
     assert response.status_code == 200
-    assert response.json() == {"subject": "auth0|test-user"}
+    assert response.json() == {"subject": "auth0|test-user", "roles": ["user"]}


 @pytest.mark.asyncio
@@ -401,7 +427,7 @@ async def test_active_handler_sees_the_verified_principal(


 def test_describe_caller() -> None:
-    principal = AuthenticatedPrincipal("auth0|abc", "i", ("a",), frozenset(), frozenset())
+    principal = AuthenticatedPrincipal("auth0|abc", "i", ("a",), frozenset(), frozenset(), frozenset({"user"}))
     assert describe_caller(principal) == "auth0|abc"
     assert describe_caller(None) == "anonymous"

@@ -436,6 +462,6 @@ def test_pbest_operations_keep_their_paths() -> None:


 def test_principal_is_immutable() -> None:
-    principal = AuthenticatedPrincipal("s", "i", ("a",), frozenset(), frozenset())
+    principal = AuthenticatedPrincipal("s", "i", ("a",), frozenset(), frozenset(), frozenset({"user"}))
     with pytest.raises(AttributeError):
         principal.subject = "other"  # type: ignore[misc]
```

| Test | Proves |
|---|---|
| `test_valid_token_yields_principal` (extended) | A machine token with no roles claim still gets `{"user"}` |
| `test_roles_claim_adds_to_the_default_role` ×5 | Extra roles are added; `user` isn't duplicated; non-strings are dropped; a non-list claim or an empty list leaves just `user` |
| `test_no_header_is_anonymous` (extended) | Anonymous gets `roles: None`, meaning no role, and a 200 |
| `test_valid_token_reaches_handler` (extended) | The handler receives `roles == ["user"]` through `OptionalPrincipal` |

### 4.3 `docs/index.md`: add under *Authentication (optional)*, before *What is accepted*

```markdown
### Roles

Every verified caller holds the role `user`; an anonymous caller holds no role. If the token carries the
`https://api.biosimulations.org/roles` claim (tokens issued to a logged-in person on this tenant do), those Auth0
roles are added, for example `{"user", "admin"}`. Roles identify the caller only: no endpoint requires a role, and
every endpoint remains available anonymously.
```

### 4.4 `CLAUDE.md`: append to the **Authentication** paragraph

```text
Every principal carries `roles`: always `DEFAULT_ROLE` ("user", the tenant role owned by auth0-pulumi's
biosim-platform stack) plus any names in the `ROLES_CLAIM` (`https://api.biosimulations.org/roles`) claim written by
the tenant's post-login "BioSim Roles" Action. Anonymous is `principal is None`, so no role. Roles gate nothing yet;
keep the role and claim names in step with auth0-pulumi.
```

### 4.5 `.github/AUTH0_IMPLEMENTATION_PLAN.md`

- In **Non-Goals**, change "Implementing role- or scope-based authorization for current routes" to note that roles are
  now *derived* (see this plan) but still not *enforced*.
- In **Authenticated Principal Design**, add `roles: frozenset[str]` with a one-line pointer to this document.

### 4.6 Verify and commit

```bash
git add -A
make check
uv run python -m pytest tests/api/test_authentication.py -q   # Docker up: all pass
uv run python compose_api/api/openapi_spec.py && git diff --exit-code compose_api/api/spec/   # must be unchanged
git commit -m "feat(auth): every verified caller holds the tenant role 'user'; read Auth0 roles claim"
```

Live check (after `make run`, with a machine token from the Compose API Test Application): nothing is observable from
outside, because roles gate nothing. That's what the handler-level test is for. No curl output changes.

---

## 5. Part 2: codify `BioSim Roles` in `auth0-pulumi/biosim-platform`

**Why:** people logging in to BioSim get roles only from this dashboard-only Action. That's the path that will
populate the roles claim compose-api now reads, and today its logic is unreviewed, doesn't guarantee `user`, and can
fail logins.

**Verified offline:**
- `node --test` passes 6 Action tests on Node 26.
- 7 new mocked-provider Pulumi tests pass.
- `mypy` (14 files) is clean.
- Mutation checks: dropping `roles.add("user")` fails 4 Action tests; dropping the `try/catch` fails the "doesn't
  block the login" test.
- **Not verified live.** It changes a tenant-wide login hook, so follow §5.6 carefully.

> **Blast radius.** This Action runs on **every** login to the tenant, for BioSim as well as compose-api. Work on a
> branch, read every `pulumi preview --diff` in full, and do the live check (§5.6) with a test user before announcing
> anything.

### 5.1 Inventory the live Action (read-only, dashboard)

Record this before changing anything; the import in §5.4 depends on it.

1. **Actions → Library → BioSim Roles:**
   - the **Action ID** (in the URL);
   - the **runtime**;
   - each **dependency with its exact version** (the `auth0` SDK major version decides the call syntax, v4 versus
     v5; see the comment in §5.3);
   - the **secret names** (not values).
   Also copy the **full code** into `biosim-platform/actions/biosim_roles.dashboard.js`. It's a reference only;
   delete it after the diff in step 3.
2. **Actions → Triggers → post-login:** every bound Action, in order. **credentials-exchange:** confirm whether
   anything is bound. The audit's row 19 for this trigger came out garbled.
3. **Diff** the dashboard code against §5.3. Keep any behaviour §5.3 lacks (for example extra claims), or record why
   it's dropped. Known differences: §5.3 assigns `user` to *anyone* lacking it (not only users with no roles), catches
   Management API errors, and uses a dedicated least-privilege client.
4. Note which M2M application the current Action authenticates as. If it's `BioSim Management API M2M` and nothing
   else uses that client, its Management API grant can be narrowed later (§5.7).

### 5.2 Phase A: a dedicated least-privilege client

The Action needs Management API credentials to assign a role. It gets its **own** client, granted only
`update:users` (the scope `POST /api/v2/users/{id}/roles` requires). That way its secret can do nothing else, and
narrowing it never affects the BioSim backend.

Append to `biosim-platform/clients.py`:

```python
# ------------------------------------------------------------------------------------------------
# Used by the "BioSim Roles" post-login Action (actions.py) to assign the default "user" role
# ------------------------------------------------------------------------------------------------

"""Auth0 BioSim Roles Action M2M Client"""

biosim_roles_action_m2m = auth0.Client(
    "biosim_roles_action_m2m",
    app_type="non_interactive",
    description="Managed by Pulumi. Used only by the BioSim Roles post-login Action; granted update:users only.",
    grant_types=["client_credentials"],
    is_first_party=True,
    name="BioSim Roles Action",
    oidc_conformant=True,
    opts=pulumi.ResourceOptions(protect=True),
)
```

New file `biosim-platform/clientGrants.py`:

```python
"""Auth0 Client Grant resources for the BioSim Platform Pulumi program.

A client grant authorizes one application to request client-credentials tokens for one API. The
Management API grant below is deliberately narrow: the BioSim Roles Action only assigns roles to
users, which needs update:users and nothing else.
"""

import pulumi
import pulumi_auth0 as auth0

from clients import biosim_roles_action_m2m

auth0_domain = pulumi.Config("auth0").require("domain")

# ------------------------------------------------------------------------------------------------
# Used by the "BioSim Roles" post-login Action (actions.py)
# ------------------------------------------------------------------------------------------------

"""BioSim Roles Action -> Auth0 Management API (update:users only)"""

biosim_roles_action_management_grant = auth0.ClientGrant(
    "biosim_roles_action_management_grant",
    audience=f"https://{auth0_domain}/api/v2/",
    client_id=biosim_roles_action_m2m.client_id,
    scopes=["update:users"],
    subject_type="client",
    opts=pulumi.ResourceOptions(protect=True),
)
```

In `biosim-platform/__main__.py`, add `biosim_roles_action_m2m` to the `from clients import (...)` block and, after the
`resourceServers` import:

```python
from clientGrants import biosim_roles_action_management_grant
```

Then apply and store the secret:

```bash
cd ~/Github/UCHC/auth0-pulumi && git switch -c feature/biosim-roles-action
cd biosim-platform
pulumi preview --diff      # expect exactly 2 creates: the client and its grant; 0 updates, 0 deletes
pulumi up
# Dashboard → Applications → "BioSim Roles Action" → copy the Client Secret, then:
pulumi config set --secret rolesActionClientSecret     # paste when prompted; stored encrypted in the stack
```

### 5.3 The Action source: `biosim-platform/actions/biosim_roles.js`

```javascript
/**
 * BioSim Roles (post-login Action). Managed by Pulumi: biosim-platform/actions.py. Edit here, not in the dashboard.
 *
 * Makes sure every user who logs in to this tenant holds the tenant role "user" (roles.py: biosim_user_role), and
 * lists the user's role names in the ROLES_CLAIM claim on the access and ID tokens. compose-api reads that claim
 * (compose_api/authentication.py: ROLES_CLAIM) and also grants "user" itself, so these names are a contract with it.
 *
 * Secrets (set by Pulumi, write-only): AUTH0_DOMAIN, CLIENT_ID, CLIENT_SECRET (the "BioSim Roles Action" M2M client,
 * granted only update:users on the Management API), USER_ROLE_ID (the Auth0 id of the "user" role).
 */
const ROLES_CLAIM = "https://api.biosimulations.org/roles";
const EMAIL_CLAIM = "https://api.biosimulations.org/email";
const DEFAULT_ROLE = "user";

function managementClient(secrets) {
  const { ManagementClient } = require("auth0");
  return new ManagementClient({
    domain: secrets.AUTH0_DOMAIN,
    clientId: secrets.CLIENT_ID,
    clientSecret: secrets.CLIENT_SECRET,
  });
}

async function run(event, api, makeClient) {
  const roles = new Set(event.authorization?.roles ?? []);
  if (!roles.has(DEFAULT_ROLE)) {
    try {
      // auth0 SDK v4 call; on v5 it is `.users.roles.assign(event.user.user_id, { roles: [...] })`.
      await makeClient(event.secrets).users.assignRoles(
        { id: event.user.user_id },
        { roles: [event.secrets.USER_ROLE_ID] },
      );
    } catch (err) {
      // Never block a login over this. The next login retries, and compose-api grants "user" to every verified
      // caller regardless of this claim.
      console.log(`BioSim Roles: could not assign "${DEFAULT_ROLE}" to ${event.user.user_id}: ${err?.message ?? err}`);
    }
    // event.authorization.roles was read before this login's assignment, so add the role for this token too.
    roles.add(DEFAULT_ROLE);
  }
  const claim = [...roles].sort();
  api.accessToken.setCustomClaim(ROLES_CLAIM, claim);
  api.idToken.setCustomClaim(ROLES_CLAIM, claim);
  if (event.user.email) {
    api.accessToken.setCustomClaim(EMAIL_CLAIM, event.user.email);
  }
}

exports.onExecutePostLogin = (event, api) => run(event, api, managementClient);
exports.run = run; // for tests only; Auth0 invokes onExecutePostLogin
```

Behaviour, and the reason for each part:

| Behaviour | Why |
|---|---|
| Assigns `user` to anyone lacking it, **including an `admin`** | The goal is "authenticated means `user`", with no exceptions |
| No Management API call when `user` is already held | The call happens once per user, on first login, which keeps Management API usage and M2M token quota negligible |
| `try/catch` around the call, then log | A Management API outage must never block BioSim logins, which the audit flagged. The next login retries, and compose-api grants `user` regardless |
| Adds `user` to the claim on the assigning login | `event.authorization.roles` is read before this login's assignment. Without this, the first token would lack `user` |
| Sorted claim | Deterministic tokens, which makes tests and debugging easier |
| `run` exported alongside `onExecutePostLogin` | Lets tests inject a fake Management client. Auth0 only calls `onExecutePostLogin` |

Tests, in the new file `biosim-platform/actions/biosim_roles.test.js`. Run them with
`node --test biosim-platform/actions/`; they need no npm install, because the SDK is only loaded in production:

```javascript
// Run with: node --test biosim-platform/actions/
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { run } = require("./biosim_roles.js");

const ROLES_CLAIM = "https://api.biosimulations.org/roles";
const SECRETS = { AUTH0_DOMAIN: "t.example", CLIENT_ID: "id", CLIENT_SECRET: "s", USER_ROLE_ID: "rol_user" };

function harness(options) {
  const { roles, fail = false } = options;
  // Not a destructuring default: `email: undefined` must mean "no email", and a default would replace it.
  const email = "email" in options ? options.email : "a@b.c";
  const assigned = [];
  const claims = { access: {}, id: {} };
  const event = { user: { user_id: "auth0|u1", email }, authorization: roles === undefined ? undefined : { roles }, secrets: SECRETS };
  const api = {
    accessToken: { setCustomClaim: (k, v) => { claims.access[k] = v; } },
    idToken: { setCustomClaim: (k, v) => { claims.id[k] = v; } },
  };
  const makeClient = () => ({
    users: {
      assignRoles: async (params, body) => {
        if (fail) throw new Error("Management API unavailable");
        assigned.push({ params, body });
      },
    },
  });
  return { event, api, makeClient, assigned, claims };
}

test("a user with no roles is assigned 'user' and the token says so", async () => {
  const h = harness({ roles: [] });
  await run(h.event, h.api, h.makeClient);
  assert.deepEqual(h.assigned, [{ params: { id: "auth0|u1" }, body: { roles: ["rol_user"] } }]);
  assert.deepEqual(h.claims.access[ROLES_CLAIM], ["user"]);
  assert.deepEqual(h.claims.id[ROLES_CLAIM], ["user"]);
});

test("missing event.authorization is treated as no roles", async () => {
  const h = harness({ roles: undefined });
  await run(h.event, h.api, h.makeClient);
  assert.equal(h.assigned.length, 1);
  assert.deepEqual(h.claims.access[ROLES_CLAIM], ["user"]);
});

test("a user who already holds 'user' causes no Management API call", async () => {
  const h = harness({ roles: ["user", "admin"] });
  await run(h.event, h.api, h.makeClient);
  assert.equal(h.assigned.length, 0);
  assert.deepEqual(h.claims.access[ROLES_CLAIM], ["admin", "user"]);
});

test("an admin without 'user' gets it added, keeping 'admin'", async () => {
  const h = harness({ roles: ["admin"] });
  await run(h.event, h.api, h.makeClient);
  assert.equal(h.assigned.length, 1);
  assert.deepEqual(h.claims.access[ROLES_CLAIM], ["admin", "user"]);
});

test("a Management API failure does not block the login", async () => {
  const h = harness({ roles: [], fail: true });
  await run(h.event, h.api, h.makeClient); // must not throw
  assert.deepEqual(h.claims.access[ROLES_CLAIM], ["user"]);
});

test("the email claim is set only when the user has an email", async () => {
  const withEmail = harness({ roles: ["user"] });
  await run(withEmail.event, withEmail.api, withEmail.makeClient);
  assert.equal(withEmail.claims.access["https://api.biosimulations.org/email"], "a@b.c");
  const without = harness({ roles: ["user"], email: undefined });
  await run(without.event, without.api, without.makeClient);
  assert.equal("https://api.biosimulations.org/email" in without.claims.access, false);
});
```

### 5.4 Phase B: adopt the existing Action (import), then change it

Import **before** declaring it in code, so Pulumi adopts the live Action instead of creating a second
`BioSim Roles`. `pulumi import` protects imported resources by default.

```bash
cd ~/Github/UCHC/auth0-pulumi/biosim-platform
pulumi import auth0:index/action:Action biosim_roles_action "<ACTION_ID from 5.1>"
pulumi import auth0:index/triggerAction:TriggerAction biosim_roles_post_login "post-login::<ACTION_ID>"
```

Secrets can't be imported: Auth0 never returns their values. The code below sets them write-only, so the first
update re-provisions all four.

New file `biosim-platform/actions.py`:

```python
"""Auth0 Action resources for the BioSim Platform Pulumi program.

BioSim Roles (post-login) makes every user who logs in to this tenant hold the tenant role "user"
(roles.py: biosim_user_role) and lists the user's role names in the
https://api.biosimulations.org/roles claim. compose-api reads that claim
(compose_api/authentication.py: ROLES_CLAIM), so the role and claim names are a contract with it.
The source lives in actions/biosim_roles.js, with tests in actions/biosim_roles.test.js
(`node --test biosim-platform/actions/`).
"""

from pathlib import Path

import pulumi
import pulumi_auth0 as auth0

from clientGrants import auth0_domain
from clients import biosim_roles_action_m2m
from roles import biosim_user_role

# Set once with: pulumi config set --secret rolesActionClientSecret  (value: the "BioSim Roles Action"
# application's client secret, from the dashboard after the client is first created).
roles_action_client_secret = pulumi.Config().require_secret("rolesActionClientSecret")

# ------------------------------------------------------------------------------------------------
# Post-login: BioSim Roles
# ------------------------------------------------------------------------------------------------

"""Auth0 BioSim Roles Action"""

biosim_roles_action = auth0.Action(
    "biosim_roles_action",
    code=(Path(__file__).parent / "actions" / "biosim_roles.js").read_text(),
    # Pin to the exact version the dashboard Action uses today (Step 2.1); never "latest".
    dependencies=[{"name": "auth0", "version": "4.0.0"}],
    deploy=True,
    name="BioSim Roles",
    runtime="node22",
    # Write-only: the values never reach Pulumi state. Bump secrets_wo_version to push a changed value.
    secrets_wos=[
        {"name": "AUTH0_DOMAIN", "value": auth0_domain},
        {"name": "CLIENT_ID", "value": biosim_roles_action_m2m.client_id},
        {"name": "CLIENT_SECRET", "value": roles_action_client_secret},
        {"name": "USER_ROLE_ID", "value": biosim_user_role.id},
    ],
    secrets_wo_version=1,
    supported_triggers={"id": "post-login", "version": "v3"},
    opts=pulumi.ResourceOptions(protect=True),
)

"""Binds BioSim Roles to post-login. TriggerAction (singular) owns only this binding, so any other
post-login Actions bound in the dashboard are left alone -- unlike TriggerActions, which owns the list."""

biosim_roles_post_login = auth0.TriggerAction(
    "biosim_roles_post_login",
    action_id=biosim_roles_action.id,
    trigger="post-login",
    opts=pulumi.ResourceOptions(protect=True),
)
```

Before running `pulumi up`, fill in:
- **`dependencies` version:** the exact `auth0` version from §5.1. `"4.0.0"` is a placeholder that satisfies the
  tests, and a test fails on `"latest"`. If the live Action uses SDK **v5**, change the call in §5.3 to
  `.users.roles.assign(event.user.user_id, { roles: [...] })`.
- **`TriggerAction` (singular):** it owns only this binding. The plural `TriggerActions` owns the *whole* post-login
  list and would unbind any other Action not listed.

In `biosim-platform/__main__.py`, after the `clientGrants` import:

```python
from actions import biosim_roles_action, biosim_roles_post_login
```

```bash
pulumi preview --diff
# Expect: ~ update biosim_roles_action (code, dependencies, secrets); the binding unchanged.
# STOP if it shows a create/replace of biosim_roles_action (the import didn't take) or any delete.
pulumi up
```

### 5.5 Offline tests for the Pulumi program

`biosim-platform/tests/conftest.py`: the program now reads config, so give the mocked runtime some. Add this directly
after the existing `pulumi.runtime.set_mocks(...)` line. The key prefix is the mock's project name,
`auth0ts-pulumi`:

```python
# Config the program requires; under mocks nothing is read from the real stack or ESC environment.
pulumi.runtime.set_all_config(
    {
        "auth0:domain": "unit-test.example.auth0.com",
        "auth0ts-pulumi:rolesActionClientSecret": "unit-test-secret",
    },
    ["auth0ts-pulumi:rolesActionClientSecret"],
)
```

New file `biosim-platform/tests/test_roles_action.py`:

```python
"""Offline tests for the BioSim Roles post-login Action and its narrow Management API grant.

The role and claim names checked here are a contract with compose-api, which grants "user" to every
verified caller and reads the https://api.biosimulations.org/roles claim.
"""

from pathlib import Path

import pulumi

ACTION_SOURCE = Path(__file__).resolve().parent.parent / "actions" / "biosim_roles.js"


@pulumi.runtime.test
def test_action_is_bound_to_post_login(program):
    def check(args):
        action_id, binding_action_id, trigger = args
        assert binding_action_id == action_id
        assert trigger == "post-login"

    return pulumi.Output.all(
        program.biosim_roles_action.id,
        program.biosim_roles_post_login.action_id,
        program.biosim_roles_post_login.trigger,
    ).apply(check)


@pulumi.runtime.test
def test_action_targets_post_login_on_node22(program):
    def check(args):
        runtime, triggers = args
        assert runtime == "node22"
        assert triggers["id"] == "post-login"

    return pulumi.Output.all(
        program.biosim_roles_action.runtime, program.biosim_roles_action.supported_triggers
    ).apply(check)


@pulumi.runtime.test
def test_action_deploys_the_checked_in_source(program):
    def check(code):
        assert code == ACTION_SOURCE.read_text()
        assert '"https://api.biosimulations.org/roles"' in code
        assert 'DEFAULT_ROLE = "user"' in code

    return program.biosim_roles_action.code.apply(check)


@pulumi.runtime.test
def test_action_dependencies_are_pinned(program):
    def check(dependencies):
        for dependency in dependencies:
            assert dependency["version"] not in ("", "latest"), dependency

    return program.biosim_roles_action.dependencies.apply(check)


@pulumi.runtime.test
def test_user_role_id_secret_is_the_managed_user_role(program):
    def check(args):
        secrets, user_role_id, user_role_name = args
        values = {secret["name"]: secret["value"] for secret in secrets}
        assert set(values) == {"AUTH0_DOMAIN", "CLIENT_ID", "CLIENT_SECRET", "USER_ROLE_ID"}
        assert values["USER_ROLE_ID"] == user_role_id
        assert user_role_name == "user"

    return pulumi.Output.all(
        program.biosim_roles_action.secrets_wos, program.biosim_user_role.id, program.biosim_user_role.name
    ).apply(check)


@pulumi.runtime.test
def test_management_grant_is_update_users_only(program):
    def check(args):
        scopes, audience, grant_client_id, client_id = args
        assert list(scopes) == ["update:users"]
        assert audience.endswith("/api/v2/")
        assert grant_client_id == client_id

    return pulumi.Output.all(
        program.biosim_roles_action_management_grant.scopes,
        program.biosim_roles_action_management_grant.audience,
        program.biosim_roles_action_management_grant.client_id,
        program.biosim_roles_action_m2m.client_id,
    ).apply(check)


@pulumi.runtime.test
def test_roles_action_client_is_client_credentials_only(program):
    def check(grant_types):
        assert list(grant_types) == ["client_credentials"]

    return program.biosim_roles_action_m2m.grant_types.apply(check)
```

```bash
cd ~/Github/UCHC/auth0-pulumi
MYPYPATH=biosim-platform uv run mypy biosim-platform                  # what CI runs
cd biosim-platform && uv run --with pytest python -m pytest tests -m "not live" -q
node --test actions/
```

> **Pre-existing failures (not caused by this work):** `test_program_evaluates_without_error` and
> `test_client_credentials_reference_the_matching_client` fail on the **unchanged** repo, because they reference
> `program.client`, which no longer exists. Fix or delete them in a separate commit. pytest also isn't declared in any
> dependency group, so add it to `biosim-platform`'s `dev` group and to CI.

### 5.6 Live verification (with a test user)

1. **Create a test user:** Dashboard → User Management → Users → Create, in a database connection. It starts with
   **no roles**.
2. **Log in as that user** through the BioSim app, or through Authentication → Database → your connection → **Try**.
3. **Check the user:** Users → test user → **Roles** shows `user`.
4. **Check the token:** decode the ID token (see §6.4); `https://api.biosimulations.org/roles` is `["user"]`.
5. **Check an existing admin:** log in again as an existing admin; it succeeds, and their roles now include `user`.
6. **Check for failures:** Monitoring → Logs: look for failed logins (`f`) since the deploy, and for
   `BioSim Roles: could not assign` lines in the Action's logs.
7. **Clean up:** delete the test user.

**Rollback:**
- **Code problem:** Actions → Library → BioSim Roles → *Version History* → roll back to the previous version (live in
  seconds). Then `git revert` and `pulumi up` to bring state back in line.
- **Remove the binding:** `pulumi state unprotect <urn>` first. Bindings are protected, so a plain delete is refused.

### 5.7 Follow-ups after it's live

- Delete `actions/biosim_roles.dashboard.js`.
- If `BioSim Management API M2M` was used only by the old Action, remove its Management API grant or narrow it. It's
  not in Pulumi, so import it first with `pulumi import auth0:index/clientGrant:ClientGrant … "cgr_…"`.
- Update `biosim-platform/README.md`: add `actions.py`, `clientGrants.py` and `actions/` to the tree. Its *Roles*
  section should say "`user` is assigned by the BioSim Roles Action (actions.py)", replacing "assignments live in the
  dashboard" for this role.

---

## 6. Part 3 (conditional): let people call compose-api as themselves

### 6.0 Decision gate
Do this only if a person using a BioSim front end should call compose-api **with their own identity**, for
attribution or future per-user policy. Today every compose-api caller is anonymous or a machine, and Parts 1–2 already
meet the goal for them. **Not prototyped:** this depends on the decision, and on a front-end repo outside this
workspace.

### 6.1 `auth0-pulumi/biosim-platform/__main__.py`: export the SPA's client id

```python
pulumi.export("biosim_spa_client_id", auth0_biosim_platform.client_id)
```

### 6.2 `auth0-pulumi/compose-api/clientGrants.py`: user-delegated grant for the SPA

The SPA client belongs to the biosim-platform stack, so reference it with a `StackReference` rather than
re-declaring it. Two stacks declaring one client would fight over it.

```python
biosim_platform_stack = pulumi.StackReference("<org>/biosim-platform/biosim-platform-auth0")

"""BioSimulation Platform SPA -> Compose-API (production), on behalf of the logged-in person"""

biosim_spa_compose_user_grant = auth0.ClientGrant("biosim_spa_compose_user_grant",
    audience=compose_auth0_api.identifier,
    client_id=biosim_platform_stack.get_output("biosim_spa_client_id"),
    scopes=[],
    subject_type="user",
    opts = pulumi.ResourceOptions(protect=True))
```

Import it in `compose-api/__main__.py`, then run `pulumi preview` (expect 1 create) and `pulumi up`. Replace
`<org>` with the value from `pulumi whoami` or `pulumi org get-default`.

### 6.3 Front end (outside this workspace)
Requesting a token for compose-api is a separate call from the BioSim API token, because a token has one API
audience. For example, with auth0-spa-js:
`getAccessTokenSilently({ authorizationParams: { audience: "https://api.compose.cam.uchc.edu" } })`. Send the result
as `Authorization: Bearer …` on compose-api calls only.

### 6.4 Verify
Decode the token locally; never paste tokens into jwt.io:
```bash
python3 -c 'import sys,base64,json; p=sys.argv[1].split(".")[1]; print(json.dumps(json.loads(base64.urlsafe_b64decode(p+"="*(-len(p)%4))),indent=2))' "$TOKEN"
```

Expect:
- `sub` starting `auth0|` (a person), and `aud` including `https://api.compose.cam.uchc.edu`;
- `https://api.biosimulations.org/roles` of `["user"]`, or more;
- a 200 from compose-api, with the submission log line naming that `sub`.

---

## 7. Order, commits, acceptance

| Step | Repo | Depends on | Commit |
|---|---|---|---|
| Part 1 | compose-api | nothing | `feat(auth): every verified caller holds the tenant role 'user'; read Auth0 roles claim` |
| 5.2 | auth0-pulumi | nothing | `feat(biosim-platform): least-privilege client for the BioSim Roles Action` |
| 5.3–5.5 | auth0-pulumi | 5.2 applied and secret set | `feat(biosim-platform): manage BioSim Roles in Pulumi; always assign 'user', never block login` |
| 5.7 | auth0-pulumi | 5.6 passed | `chore(biosim-platform): retire old Action credentials; README` |
| Part 3 | auth0-pulumi + front end | decision, Part 2 | `feat(compose-api): user-delegated access for the BioSim SPA` |

**Acceptance**
- [ ] Anonymous request: 200, `principal is None`, no role. *(Part 1 tests)*
- [ ] Any verified token: `"user" in principal.roles`, machine tokens included. *(Part 1 tests)*
- [ ] Roles from the `https://api.biosimulations.org/roles` claim are added; malformed claims are ignored, not 401.
      *(Part 1 tests)*
- [ ] OpenAPI spec unchanged; pbest unaffected. *(Part 1 §4.6)*
- [ ] `BioSim Roles` is declared in Pulumi, imported not duplicated, and bound with a singular `TriggerAction`.
      *(§5.4 preview)*
- [ ] A new user gets `user` on first login, and that first token already carries it. *(§5.6 steps 1–4; Action tests)*
- [ ] An existing admin gains `user` and keeps `admin`. *(§5.6 step 5; Action tests)*
- [ ] A Management API failure doesn't block a login. *(Action tests)*
- [ ] The Action's credentials can only `update:users`. *(Pulumi test; §5.2 preview)*
- [ ] *(Part 3 only)* A logged-in person's compose-api token carries `sub = auth0|…` and the roles claim. *(§6.4)*

## 8. Risks and open questions

| Risk or question | Mitigation or owner |
|---|---|
| The Action runs on every tenant login, so a bug affects all BioSim users | Tests, a test user first, and version-history rollback (§5.6) |
| `update:users` also allows editing user profiles | It's the minimum scope for role assignment, the client is dedicated, and its secret is write-only in the Action |
| Unknown `auth0` SDK version in the live Action | §5.1 records it; §5.3 notes the v4/v5 call difference |
| Unknown other post-login and credentials-exchange bindings (audit row 19 garbled) | §5.1 step 2; the singular `TriggerAction` leaves them alone |
| Dropping behaviour the dashboard code has that §5.3 lacks | §5.1 step 3 diff |
| The Management API token is fetched on each assigning login | Only the first login per user; optionally cache it with `api.cache` if volume grows |
| Should compose-api ever *require* a role? | Out of scope; decide per endpoint later on top of `principal.roles` |

## Verification status

| Part | What ran | Result |
|---|---|---|
| 1 | pre-commit, `mypy --strict` (91 files), auth tests, spec regeneration, mutation | clean; 54 passed (1 Docker-only test not run); spec identical; 6 tests catch a missing default role |
| 2 | `node --test` (Node 26), mocked Pulumi tests, CI's mypy call, mutation | 6/6 Action tests; 7/7 new Pulumi tests; 14 files clean; both mutations caught. **Not run against the live tenant** |
| 3 | none | design only; needs the §6.0 decision |
