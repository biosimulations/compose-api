# Calling the Compose API

Authentication is optional on the existing business endpoints. The API accepts anonymous requests there, and a valid access token identifies who is calling. It does not change which simulations, statuses, or result files you can read. `GET /auth/me` requires authentication.

## Verify the authenticated identity

`GET /auth/me` requires a valid Compose-audience bearer access token. It returns `issuer`, `subject`, `audience`,
`roles`, `scopes`, and `permissions`, with sorted arrays and `Cache-Control: no-store`. It never returns the token,
email, or other account/profile details. Use `(issuer, subject)` as the identity key, not email.

Missing or invalid credentials receive the same 401 and `WWW-Authenticate: Bearer` described below. A valid
machine token also works: this endpoint reflects the existing principal contract, not a human-only restriction.
The generated client's `get_current_principal` operation requires `AuthenticatedClient`; existing business
operations still accept either `Client` or `AuthenticatedClient`.

This endpoint proves server recognition of a credential; it does not prove persisted Auth0 role membership or
grant ownership of simulations. The `compose-api` CLI uses it to confirm a sign-in (see "CLI sessions" below).
Native-client infrastructure and live provider validation have separate deployment gates.

## Authentication at a glance

Omit the `Authorization` header and the request is anonymous.

Send one header when you want the call attributed to an authenticated caller:

```http
Authorization: Bearer <ACCESS_TOKEN>
```

`<ACCESS_TOKEN>` must be an OAuth access token for this API (see below). The scheme is case-insensitive (`Bearer` and `bearer` both work). Send the header once.

A header that is present but not acceptable is **401 Unauthorized**. The body is `{"detail": "Invalid authentication credentials"}`, with `WWW-Authenticate: Bearer`. The API does not fall back to anonymous. That includes:

- a scheme other than Bearer, an empty token, or more than one `Authorization` header
- a malformed token, a bad signature, or an algorithm other than RS256
- an expired token, or a token whose issuer or audience does not match this server

To call anonymously, leave the header out.

`GET /health` and `GET /version` ignore the header. A missing, valid, or garbage `Authorization` value still returns 200.

## Authentication does not make a simulation private

A valid access token identifies the caller. It does not attach the simulation to that caller, and it does not hide the simulation from anyone else.

These routes look up a simulation by its numeric id and do not check who submitted it:

- `GET /results/simulation/status?simulation_id=<id>`
- `GET /results/simulations/status/batch`
- `GET /results/simulation/results/file?simulation_id=<id>`

Anyone who has the id can read status and, when the results file exists, download it. Anonymous and authenticated callers see the same record. A missing simulation, or results that are not ready yet, is 404.

Do not treat bearer authentication as an access-control boundary for simulation status or results.

## Human callers

This API does not register or sign in users; Auth0 does. There are two supported ways for a person to get an access
token for it:

- The [`compose-api` command-line client](cli.md). It signs you up or in on Auth0's hosted pages (email and password,
  or Google), keeps the session in your operating system's credential store, renews it, and calls this API for you.
- BioSim's web login. The client that completed that login requests an **access token** whose audience is the Compose
  API identifier for the environment you are calling, and sends it in the `Authorization` header above.

When that client holds a refresh token, use the client's refresh flow to obtain a new access token before the current one expires. Send the new access token to this API. Do not send the refresh token here. This API does not issue, refresh, or revoke tokens.

## Service callers

A service uses the OAuth 2.0 client-credentials grant. The Auth0 application must be allowed to request the Compose API audience for that environment. Ask the tenant for a new access token when the current one expires. Client credentials do not return a refresh token.

```bash
curl --request POST \
  --url "https://<AUTH0_DOMAIN>/oauth/token" \
  --header "content-type: application/json" \
  --data '{
    "grant_type": "client_credentials",
    "client_id": "<CLIENT_ID>",
    "client_secret": "<CLIENT_SECRET>",
    "audience": "<COMPOSE_API_AUDIENCE>"
  }'
```

Use the `access_token` from the response as `<ACCESS_TOKEN>`. `<AUTH0_DOMAIN>` is the bare host configured on the server (`AUTH0_DOMAIN`, no `https://` and no trailing slash). `<COMPOSE_API_AUDIENCE>` is that server's `AUTH0_AUDIENCE`.

## Local and production audiences

The audience is the API identifier the token was issued for. It is not the URL you call.

The checked-in deployments expect:

| Environment | API host | `AUTH0_AUDIENCE` |
|---|---|---|
| Production (`kustomize/config/compose-api-rke/api.env`) | `https://compose.cam.uchc.edu` | `https://api.compose.cam.uchc.edu` |
| Local cluster (`kustomize/overlays/compose-api-local/ingress.yaml`, `auth0.env`) | `https://api.compose-api-local` | `https://api.compose.local` |

Those two audiences are not interchangeable. A token minted for one is rejected by a server configured with the other. Both of those deployments currently use the same `AUTH0_DOMAIN` (`dev-bu7yo7484tyxu6a1.us.auth0.com`); sharing a tenant does not make the audiences interchangeable.

A server started from `assets/dev/config/.dev_env` uses whatever `AUTH0_AUDIENCE` is set there. Match the token to that value.

## When Auth0 is not configured

`AUTH0_DOMAIN` and `AUTH0_AUDIENCE` are ordinary settings, not secrets. If either one is empty, or both are, verification is off. The two cases behave the same:

- a request with no `Authorization` header still succeeds as anonymous
- a request that sends a bearer token receives the same 401 as any other rejected credential

`/health` and `/version` are unchanged.

## Roles

A verified caller is recorded with the role `user`. If the access token includes the `https://api.biosimulations.org/roles` claim (tokens for a person signed in through BioSim do; client-credentials tokens do not), those role names are recorded as well. An anonymous caller has no role.

Roles identify the caller. No endpoint checks them. Do not assume a role grants or denies access unless this API later documents that check.

## Do not

**Do not use the Resource Owner Password Credentials grant** (the password grant). Collecting a user's password in your client is not a supported way to call this API. Human callers sign in through the `compose-api` CLI or BioSim, on Auth0's own pages, and send the resulting access token. Services use client credentials.

**Do not send an ID token.** An ID token's audience is the client application, not the Compose API, so this API rejects it. Send the access token whose audience is the Compose API identifier for the environment you are calling.

### CLI sessions and local logout

The native CLI's `auth login` and `auth signup` persist a validated session in an approved OS credential store.
Public profiles are separate from server configuration. Configure the native client ID in the CLI profile before
signing in. The CLI never accepts passwords or tokens as command arguments and never falls back to a token file.

`compose-api auth status` inspects local expiry without contacting Auth0 or renewing credentials; `--json` emits
non-secret metadata. A local identity is not proof of current API access, so the output labels the API's last
confirmation as a stored fact. `auth status --verify` renews the session if needed and asks `GET /auth/me`; a network
failure there is reported as such, not as a sign-out. Sign-in ends with the same check: it succeeds only once the API
has confirmed the identity, and if the API cannot be reached it keeps the saved session, says it is unconfirmed and
exits non-zero.

`compose-api simulators list`, `simulations status ID` and `simulations submit FILE` call the existing operations
through the generated client with the stored session. With no session they fail (exit 3); they never fall back to
anonymous access or start a sign-in on their own. A read the API rejects with 401 is renewed and retried once; a
403 is final. A submission is never sent twice: after a timeout or server error its outcome is reported as unknown.
The bearer is sent only to the profile's API origin and these operations, never to Auth0 or a redirect.

`compose-api auth logout` attempts bounded refresh-token revocation, then deletes local credentials even when the
provider is unavailable. `--local-only` performs only local deletion. Revocation failure is reported with exit 5;
failed local deletion is exit 6 and must be retried after unlocking/repairing the OS store. No secret is retained in a
revocation retry queue. Already-issued access tokens can remain valid until expiry, and neither command clears
Auth0 or Google browser sessions.

Access and refresh tokens live together in one versioned keyring record. The service identifier begins with
`compose-api.cli.v1.` and ends in the public configuration binding digest; it contains no email. A changed issuer,
client, audience, API origin or requested scope set selects a different session. Identical profile bindings share a
session deliberately. macOS Keychain and Linux Secret Service are allowlisted. Windows Credential Manager is
allowlisted with a single native credential overwrite, but a credential holds 2560 bytes of UTF-16 and a realistic
session is about 3400, so persistent sessions do not fit there yet and the save fails explicitly; on Windows use
`--ephemeral-auth`. Unknown, chained, plaintext and null backends are refused. Keyrings protect credentials at rest, not
against a compromised operating-system account. Python cannot promise memory zeroization.

Non-secret lock/generation/journal files live under the platform user-state directory, in `compose-api/sessions`.
POSIX directories/files require 0700/0600 and current-user ownership. Windows uses a protected owner-only ACL.
Do not delete these files to reset a session while another command is running: retained generation tombstones
prevent a late login callback from resurrecting a logged-out session. Use `auth logout --local-only` instead.
Corrupt credential records and corrupt private metadata are removable through local logout; unsafe file ownership,
permissions or symlinks must be repaired by the local user first.

Refresh holds the binding's process lock and journals the attempt before any provider request. Other processes
reread the successor rather than rotate twice. If Auth0 cannot even be discovered, the refresh token was not sent
and the session stays. Once the refresh request may have left the machine, a crash or a failed answer with no
durably stored successor requires a fresh sign-in; the old refresh credential is never replayed. An already stored
complete successor can recover an interrupted metadata cleanup. Login uses a separate transaction lock and commits only if its starting generation still matches.
A failed/locked backend stops persistent sign-in before the browser when detectable; there is no insecure fallback.
On a host without a usable credential store, add `--ephemeral-auth` to an API command: it signs in for that one
command, requests no refresh token, keeps the session in memory and forgets it when the command ends.

Real stores are exercised by `tests/cli/test_os_keyring.py` (opt-in: `COMPOSE_API_TEST_OS_KEYRING=1`, synthetic
records under random names, always deleted). On 2026-10-07 it passed against the macOS Keychain (macOS 27.0.1) and
GNOME Keyring's Secret Service (Debian 13, in a container), where a locked keyring was also refused before sign-in.
Crash paths use deterministic fakes. Windows Credential Manager and its ACLs, and live refresh and revocation driven by
the CLI, remain release gates; the `CLI platforms` workflow runs the same tests on Windows, and passing mocks do not
close them.
