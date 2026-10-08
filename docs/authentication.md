# Calling the Compose API

Authentication is optional. The API accepts anonymous requests, and a valid access token identifies who is calling. It does not change which simulations, statuses, or result files you can read.

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

Every route that reads something a simulation owns asks the server's read policy whether the caller may read it, and the verified caller is the one it asks about:

- `GET /results/simulation/status?simulation_id=<id>`
- `GET /results/simulations/status/batch`
- `GET /results/simulation/results/file?simulation_id=<id>`
- `GET /results/simulation/events`, `GET /results/simulation/trace` and `GET /results/simulation/trace/chrome`
- `GET /simulations` and `GET /simulations/<id>`
- `GET /datasets`, `GET /datasets/<id>` and `GET /datasets/<id>/content`

The policy lets anyone read a public simulation, and only its owner read a private one. Submitting a simulation does not record an owner yet, so every simulation is public. Anyone who has the id can read its status, events and datasets and, when the results file exists, download it. Anonymous and authenticated callers see the same record. A missing simulation, or results that are not ready yet, is 404.

Do not treat bearer authentication as an access-control boundary for simulation status or results.

## Human callers

This API does not register or sign in users. Sign in through BioSim's login. The client that completed that login then requests an **access token** whose audience is the Compose API identifier for the environment you are calling. Send that access token in the `Authorization` header above.

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

Roles identify the caller. One role is checked: the read policy lets a caller with the role `admin` read private simulations. No simulation is private yet, so today no role changes what a caller can read. Do not assume any other role grants or denies access unless this API later documents that check.

## Do not

**Do not use the Resource Owner Password Credentials grant** (the password grant). Collecting a user's password in your client is not a supported way to call this API. Human callers sign in through BioSim and send the resulting access token. Services use client credentials.

**Do not send an ID token.** An ID token's audience is the client application, not the Compose API, so this API rejects it. Send the access token whose audience is the Compose API identifier for the environment you are calling.
