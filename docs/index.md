# compose-api

[![Release](https://img.shields.io/github/v/release/biosimulations/compose-api)](https://img.shields.io/github/v/release/biosimulations/compose-api)
[![Build status](https://img.shields.io/github/actions/workflow/status/biosimulations/compose-api/main.yml?branch=main)](https://github.com/biosimulations/compose-api/actions/workflows/main.yml?query=branch%3Amain)
[![Commit activity](https://img.shields.io/github/commit-activity/m/biosimulations/compose-api)](https://img.shields.io/github/commit-activity/m/biosimulations/compose-api)
[![License](https://img.shields.io/github/license/biosimulations/compose-api)](https://img.shields.io/github/license/biosimulations/compose-api)

An API server for reproducible biological workflows and cosimulations.

## Authentication (optional)

Every endpoint works without credentials. Callers who have an Auth0 access token for compose-api may send it; the
API then verifies it and knows who is calling. Sending a token does not change what an endpoint returns.

### Anonymous use (unchanged)

```bash
curl http://localhost:8000/core/simulator/list
```

No `Authorization` header means an anonymous request, exactly as before.

### Sending a token

```bash
export AUTH0_ACCESS_TOKEN='<your access token>'   # never commit a token or paste one into an issue
curl -H "Authorization: Bearer ${AUTH0_ACCESS_TOKEN}" http://localhost:8000/core/simulator/list
```

With the generated client, use `AuthenticatedClient(base_url=..., token=...)` in place of `Client`. In Swagger UI
(`/docs`), use **Authorize** and paste the token without the `Bearer ` prefix.

A header that is present but not valid is rejected with `401 Unauthorized` and `WWW-Authenticate: Bearer`. It is
**never** treated as anonymous. That covers a scheme other than `Bearer`, an empty or malformed token, an expired
token, a bad signature, and the wrong issuer or audience. To call anonymously, leave the header out entirely.

`/health` and `/version` ignore credentials.

### Roles

Every verified caller holds the role `user`; an anonymous caller holds no role. If the token carries the
`https://api.biosimulations.org/roles` claim (tokens issued to a logged-in person on this tenant do), those Auth0
roles are added, for example `{"user", "admin"}`. Roles identify the caller only: no endpoint requires a role, and
every endpoint remains available anonymously.

### What is accepted

Only RS256-signed Auth0 **access tokens** issued for this API's audience are accepted. These are rejected:

- ID tokens: their audience is the client id, not the API
- Auth0 Management API tokens, or tokens issued for any other API
- tokens signed with HS256 or any algorithm other than RS256

### Local configuration

Set these in `assets/dev/config/.dev_env`. They are not secrets, and no Auth0 client secret is needed to verify
tokens:

```text
# bare host: no https:// and no trailing slash
AUTH0_DOMAIN=<tenant>.us.auth0.com
# the API Identifier, exactly as shown under Applications -> APIs
AUTH0_AUDIENCE=<Auth0 API Identifier>
```

Restart the server after changing them, because settings are cached at startup. If either value is empty, the API
still serves anonymous requests but rejects every supplied token with 401.

### Auth0 tenant setup

This is done once, in the Auth0 Dashboard, separately from the application:

1. **Applications -> APIs -> Create API.** Choose an Identifier, which becomes `AUTH0_AUDIENCE` and cannot be
   changed later, and select the **RS256** signing algorithm.
2. Get a development token from the API's **Test** tab, or from an application authorized for the API.
3. Use a separate API (and ideally a separate tenant) for production, so a development token is never accepted in
   production.
