# Web UI sign-in: a PKCE single-page app, no backend-for-frontend

**Status (2026-10-22): proposed; to resume the week of 2026-10-26. Blocked on W1 (the Auth0 SPA application, Novrus).**
**(2026-10-22, later: W1 requested in UCHHPC/auth0-pulumi#5. W3 and W4 are in review in one PR.)**
No code has changed for this plan yet. One PR per work item, each merged with a merge commit. The configuration
change (W2) deploys on merge, so it waits for W3 and W4 to be in a release.

| Item | What | Owner | State |
|---|---|---|---|
| W1 | The Auth0 Single Page Application | Novrus (auth0-pulumi) | requested (UCHHPC/auth0-pulumi#5) |
| W2 | `AUTH0_SPA_CLIENT_ID` in the deployments | us | waits on W1 |
| W3 | Webapp fixes: return target, token allowlist, sign-up, identity, expired sessions | us | in review |
| W4 | Security headers on `/ui`, Content-Security-Policy report-only first | us | in review |
| W5 | Documentation | us | open |

## Findings (2026-10-22)

1. **The web UI already has sign-in; nothing switches it on.**
   - `webapp/app/plugins/webapp-config.client.ts` creates an `@auth0/auth0-vue` client: Auth0's SPA SDK, which runs
     Authorization Code with PKCE. Its options are `useRefreshTokens: true`, `cacheLocation: 'localstorage'`, and
     `redirect_uri` set to `<origin>/ui/`.
   - It does so only when `GET /webapp/config` (`compose_api/api/webapp.py`, `get_webapp_config`) returns a domain, an
     audience and an SPA client id. The client id comes from `Settings.auth0_spa_client_id`.
   - `AUTH0_SPA_CLIENT_ID` is set in neither `kustomize/config/compose-api-rke/api.env` nor
     `kustomize/overlays/compose-api-local/auth0.env`, so the "Sign in" button (`webapp/app/components/AuthMenu.vue`)
     never appears.
   - `webapp/app/composables/useApi.ts` attaches the bearer token to API requests. On a 401 it shows a "Sign-in not
     accepted" banner (`app.vue`) and continues anonymously.
2. **The platform frontend has no backend-for-frontend either.**
   - `platform/frontend` uses the same pattern: a public SPA with `@auth0/auth0-vue` and PKCE, tokens in localStorage,
     and direct bearer calls to its FastAPI resource server. compose-api's plugin was copied from it
     (`frontend/app/plugins/auth0.client.ts`).
   - Four of its ideas are worth reusing:
     - a strict origin and path allowlist before a token is attached (`frontend/app/utils/api-auth.ts`, tested in
       `frontend/tests/api-auth.test.mjs` with a mocked `createAuth0`);
     - a header `AuthMenu` with a loading skeleton, a sign-in button, and a dropdown when signed in;
     - returning to the page the person started from, through `appState.target`;
     - the tenant's Post-Login Action (`platform/auth0/actions/post-login.js`), which stamps the
       `https://api.biosimulations.org/roles` claim that `compose_api.authentication.ROLES_CLAIM` reads.
3. **A signed-in user can do nothing more than an anonymous one yet.**
   - Submissions record no owner, so every simulation is public, and `ADMIN_ROLE` is unset.
   - Only `GET /auth/me` behaves differently. Submissions log the caller's subject.
   - A token that is present but invalid is a 401, never anonymous. That is why the UI drops a rejected token.

## Decisions (Jim, 2026-10-22)

- **D1. Keep the public-client SPA with PKCE; no backend-for-frontend.**
  - Tokens stay in **localStorage, with refresh-token rotation**: reuse detection, plus an absolute and an idle
    lifetime.
  - Auth0 documents this as the choice for an SPA without a custom domain. Memory-only storage would force a redirect to
    Auth0 on every reload and every new tab, because browsers block the third-party cookies its silent-auth iframe
    needs.
  - The cost is that script injection could read the stored token. W4's Content-Security-Policy is the mitigation.
  - A FastAPI backend-for-frontend (a confidential client, with an httpOnly session cookie, so no token ever reaches the
    browser) is the strongest pattern in the IETF's draft best practice for browser-based OAuth apps. It was deferred:
    it adds server-side sessions and CSRF protection alongside the CLI's bearer path. Revisit it if the UI ever holds
    higher-value permissions.
- **D2. Scope is sign-in and sign-out only.** Stamping the owner at submission, and a "My simulations" view, remain
  [plan-observability](plan-observability.md) step 5.
- **D3. Novrus creates the Auth0 SPA application** in auth0-pulumi's compose-api stack, where he defined the CLI's
  native applications.

## Work

### W1. The Auth0 Single Page Application (Novrus, auth0-pulumi)

- Application type **Single Page Application**: token endpoint authentication `none`, grants `authorization_code` and
  `refresh_token`.
- Refresh-token **rotation on**, with a reuse interval of 0, plus an absolute and an idle lifetime.
- Allowed callback URLs and logout URLs:
  - production: `https://compose.cam.uchc.edu/ui/`
  - development: `http://localhost:4200/ui/`
  - the local cluster, `https://api.compose-api-local/ui/`, if it should offer sign-in too. That can be this
    application or a second one, his choice, since its audience is `https://api.compose.local`.
- Allowed web origins: `https://compose.cam.uchc.edu` and `http://localhost:4200`, plus the local cluster's origin if
  included.
- Allowed to request the audience `https://api.compose.cam.uchc.edu`, and the local audience if one application serves
  both.
- Connections: `Username-Password-Authentication` and `google-oauth2`, as for the CLI applications.
- The "BioSim Roles" Post-Login Action already runs for every application in the tenant.
- **Output:** the client id or ids. A public SPA client id is an identifier, not a secret.

### W2. Configuration

- Set `AUTH0_SPA_CLIENT_ID` in `kustomize/config/compose-api-rke/api.env`, and in
  `kustomize/overlays/compose-api-local/auth0.env` if the local cluster is included.
- Add it to `assets/dev/config/.dev_env_TEMPLATE`, with a comment.
- Merging the production value turns sign-in on at the next pod restart, so W3 and W4 should be in the running release
  first.

### W3. Webapp fixes

- **Return to the page the person started from.** `useAuth().login` sends `appState.target = route.fullPath`, but
  nothing reads it back.
  - First check whether auth0-vue's own router integration navigates there under `app.baseURL: '/ui/'`.
  - If it doesn't, handle the redirect callback in the plugin: navigate to the target, then remove `code` and `state`
    from the URL.
- **Token allowlist.** Attach the bearer token only when a request's origin equals `apiBase`'s, after the platform's
  `isPlatformApiRequest`. That means rejecting userinfo URLs, other schemes and lookalike hosts, and failing closed when
  the configuration is missing.
  - It applies everywhere a token is attached: the `useApi.ts` middleware, `authFetch`, `fetchContent` and
    `downloadFile`.
  - Add vitest tests in the style of `frontend/tests/api-auth.test.mjs`.
- **Sign-up.** Add a "Create account" action: `loginWithRedirect({ authorizationParams: { screen_hint: 'signup' } })`.
- **Who is signed in.**
  - Keep `user.name || user.email` on the menu button.
  - After sign-in, call `GET /auth/me` once. That way a wrong audience shows up at once, not at the first 401. Show the
    roles it returns in the dropdown.
- **Expired sessions.** When `getAccessTokenSilently` fails because the refresh token is gone or rejected
  (`login_required`, `invalid_grant`, `missing_refresh_token`):
  - treat the person as signed out;
  - show "your session expired, sign in again";
  - don't keep calling anonymously as if nothing happened.
- Correct the comment in `AuthMenu.vue`, which names `plugins/auth.client.ts`; the file is `webapp-config.client.ts`.

### W4. Security headers on `/ui`

Set these on the SPA's responses in `compose_api/api/webapp.py` (`mount_webapp`, `SpaStaticFiles`).

A `Content-Security-Policy` with:

| Directive | Value |
|---|---|
| `default-src` | `'self'` |
| `connect-src` | `'self' https://<AUTH0_DOMAIN>` |
| `frame-src` | `https://<AUTH0_DOMAIN>` |
| `img-src` | `'self' data: https:` (profile pictures) |
| `object-src` | `'none'` |
| `base-uri` | `'self'` |
| `frame-ancestors` | `'none'` |

Also send `Referrer-Policy: no-referrer` and `X-Content-Type-Options: nosniff`. Strict-Transport-Security belongs at
the ingress (`kustomize/overlays/compose-api-rke/ingress.yaml`).

Ship the policy as **`Content-Security-Policy-Report-Only` first**. Nuxt's generated inline scripts, Plotly and the
viewers may need script hashes or `'unsafe-eval'`. Measure what they need before enforcing the policy.

### W5. Documentation

- **`docs/webapp.md`, "Sign-in":**
  - D1 and its rationale;
  - the W3 behaviour;
  - the Auth0 settings from W1;
  - remove the 2026-10-13 note that no client id is published yet, once sign-in is live.
- **`docs/authentication.md`, "Human callers":** add the `/ui` sign-in alongside the CLI and BioSim's login.

## Verification

- **`make webapp-check`**, including the new vitest tests: the allowlist, the redirect target, and expired-session
  handling, all against a mocked `createAuth0`.
- **A server test:** `/webapp/config` returns the SPA client id, and `/ui` responses carry the W4 headers.
- **By hand against the real tenant**, with `make webapp-dev` and the development callback:
  - sign up and sign in, with email and with Google;
  - land back on the page you started from;
  - see your name and roles, with `/auth/me` returning 200;
  - reload, and stay signed in;
  - sign out through Auth0's `/v2/logout`, back to `/ui/`;
  - revoke the refresh token, and see the expired-session notice.
- **In production, after the release that carries W2:** repeat the smoke test at `https://compose.cam.uchc.edu/ui/`,
  and check that no CSP reports appear beyond those already accepted.

## Follow-ups (not in this plan)

- Owner at submission and a "My simulations" view ([plan-observability](plan-observability.md) step 5).
- An Auth0 custom domain, which would make memory-only token storage practical.
- A backend-for-frontend, if the UI comes to hold higher-value permissions (D1).
