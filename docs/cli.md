# Command-line client

`compose-api` is a command-line client for this API. It signs you up or in through Auth0 in your browser, keeps the
session in your operating system's credential store, and calls the API for you: the simulator catalog, a simulation's
status, and new submissions.

Signing in identifies you to the API. It does not make your simulations private: anyone with a simulation's numeric ID
can read its status and results (see [Authentication](authentication.md#authentication-does-not-make-a-simulation-private)).
Roles are labels on your identity, not access controls on simulations.

> **Before you rely on it:** the production server does not run the identity check (`GET /auth/me`) the CLI uses
> to confirm a sign-in yet, so `auth login` against production reports the session as saved but unconfirmed.
> Persistent sessions are not supported on Windows yet; use `--ephemeral-auth` there.
> [Release status](#release-status) lists everything still open.

## Install

The CLI needs Python 3.13.2 or later. It is part of the `compose-api` package, which is not published to PyPI; install
it from a tagged release with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install "git+https://github.com/biosimulations/compose-api@<release-tag>"
compose-api --version
```

The package also contains the server, so the installation is large: about 1 GB, mostly scientific libraries the CLI
never loads. `compose-api --help` starts without any of them and without any server configuration.

From a checkout, run it through the project environment:

```bash
uv run compose-api --help
uv run python -m compose_api.cli --help   # the same program
```

The bare `compose-api` command is available only when its installation is on your shell's `PATH`.
If it reports `command not found`, use `uv run compose-api` for the examples below, or activate this
checkout's environment with `source .venv/bin/activate`.

### Running against a local development server

The CLI does not start the API or its PostgreSQL database. Before running `make run`, configure
`assets/dev/config/.dev_env` using `.dev_env_TEMPLATE` and start PostgreSQL at the configured
`POSTGRES_HOST` and `POSTGRES_PORT`, with the configured credentials and database. If you already
have the local container named `compose-api-postgres`, start it with:

```bash
docker start compose-api-postgres
```

For the local Auth0 application, set these **server** values in `.dev_env`:

```dotenv
AUTH0_DOMAIN=dev-bu7yo7484tyxu6a1.us.auth0.com
AUTH0_AUDIENCE=https://api.compose.local
```

Start the server with `make run` and wait for `Application startup complete`. In another terminal,
select the local CLI settings and override the built-in local cluster URL to use this server:

```bash
export COMPOSE_API_CLI_PROFILE=local
export COMPOSE_API_CLI_API_BASE_URL=http://localhost:8000
uv run compose-api config show
uv run compose-api auth login
```

Check `config show` for existing environment overrides: the CLI's audience must match the server's
`AUTH0_AUDIENCE`, and its client ID must belong to that application. Restart the server after changing
`.dev_env`; the CLI does not read that file. Local simulation execution still requires the configured
remote SLURM backend.

If startup fails with `Connect call failed` on port 5432, PostgreSQL is unreachable; the API will not
listen on port 8000 until startup succeeds. A subsequent CLI connection error is a consequence of that
startup failure. If sign-in already saved a session, recover after starting the server with:

```bash
uv run compose-api auth status --verify
```

Use the same CLI settings as the original login to reuse that session. A missing `config.toml` is
normal when using built-in settings and environment variables.

## Profiles

A profile says which API to call and how to sign in to it. Two are built in:

| Profile | API | Auth0 audience | Client ID |
|---|---|---|---|
| `production` (default) | `https://compose.cam.uchc.edu` | `https://api.compose.cam.uchc.edu` | `1FV43fysEjhTrYYRNaMEGvCteu4g2ay4` |
| `local` | `https://api.compose-api-local` | `https://api.compose.local` | `Fp3QmULWNIhdutlBRVFm2HjPGapqdnKV` |

Both use the tenant `dev-bu7yo7484tyxu6a1.us.auth0.com`, the database connection `Username-Password-Authentication`,
the Google connection `google-oauth2` and callback port 8400. The client IDs belong to public native applications:
they are identifiers, not secrets, and there is no client secret anywhere in the CLI.

Choose a profile with `--profile NAME` (before or after the command), or `COMPOSE_API_CLI_PROFILE`. Each setting is
then taken from its environment variable, else from the profile's table in `config.toml`, else from the built-in value.
`compose-api config show` prints every effective value and where it came from.

| Setting | Environment variable | Meaning |
|---|---|---|
| `api_base_url` | `COMPOSE_API_CLI_API_BASE_URL` | The API origin. `https` only, except a loopback host (`http://localhost:8000`). No path, query or credentials. |
| `auth0_domain` | `COMPOSE_API_CLI_AUTH0_DOMAIN` | The tenant's bare host. The issuer is derived from it. |
| `auth0_audience` | `COMPOSE_API_CLI_AUTH0_AUDIENCE` | The API identifier, exactly as the server's `AUTH0_AUDIENCE`. It is not the URL you call. |
| `auth0_client_id` | `COMPOSE_API_CLI_AUTH0_CLIENT_ID` | The native application's public client ID. |
| `database_connection` | `COMPOSE_API_CLI_DATABASE_CONNECTION` | Optional: steers `--provider email` to this connection. |
| `google_connection` | `COMPOSE_API_CLI_GOOGLE_CONNECTION` | Needed for `--provider google` in the browser. |
| `callback_port` | `COMPOSE_API_CLI_CALLBACK_PORT` | The registered loopback callback port, `http://127.0.0.1:<port>/callback`. Default 8400. |
| `ca_bundle` | `COMPOSE_API_CLI_CA_BUNDLE` | Absolute path to extra CA certificates (PEM) for an API with a private CA. |

`config.toml` lives in your user configuration directory:

| System | Path |
|---|---|
| macOS | `~/Library/Application Support/compose-api/config.toml` |
| Linux | `~/.config/compose-api/config.toml` (or under `$XDG_CONFIG_HOME`) |
| Windows | `%LOCALAPPDATA%\compose-api\config.toml` |

It holds `[profiles.<name>]` tables of the settings above and nothing else. The CLI refuses a file that someone else
owns or can write to, any unknown key, and anything that looks like a secret or a token. The working directory is
never read. An example for a server you run yourself:

```toml
[profiles.dev]
api_base_url = "http://localhost:8000"
auth0_domain = "dev-bu7yo7484tyxu6a1.us.auth0.com"
auth0_audience = "https://api.compose.local"   # whatever AUTH0_AUDIENCE that server uses
auth0_client_id = "Fp3QmULWNIhdutlBRVFm2HjPGapqdnKV"
google_connection = "google-oauth2"
```

The local cluster's TLS certificate is self-signed. Point `ca_bundle` at its CA certificate rather than turning
verification off; the CLI has no option to turn it off.

## Sign up and sign in

Passwords, MFA, email verification and Google consent all happen on Auth0's pages in your own browser. The CLI never
asks for a password, and never accepts a password or token on the command line.

```bash
compose-api auth signup                     # create an email-and-password account
compose-api auth signup --provider google   # first sign-in with Google creates the account
compose-api auth login                      # returning user: choose email or Google on the page
compose-api auth login --provider google
```

The CLI listens on `127.0.0.1:8400` for Auth0's redirect, opens your browser, and waits up to five minutes. Auth0 may
ask you to confirm that you are signing in to a native application. `auth signup` always shows the sign-up page, even
when the browser is already signed in.

An email account and a Google account with the same address are two different identities. The CLI does not link
them, and nothing is merged automatically.

When the browser is on another computer, or there is no browser at all (SSH, containers):

```bash
compose-api auth login --device
```

This prints a page and a short code. Open the page on any device, enter the code, and sign in there. Only enter a code
your own command printed. With `--device`, choose email or Google on that page: the CLI cannot pre-select it.

`--no-browser` prints the sign-in link instead of opening it, for a browser on this computer that the CLI cannot
start.

Sign-in ends by asking the API who you are (`GET /auth/me`). It succeeds only when the API confirms the identity. If
the API cannot be reached, the session is still saved, the command says it is unconfirmed, and it exits non-zero; run
`compose-api auth status --verify` later.

## Your session

The session is one record in your operating system's credential store, under the service name
`compose-api.cli.v1.<digest>`. The digest covers the issuer, client ID, audience, API origin and scopes, so changing
any of them selects a different, empty session: a token is never sent to an API it was not issued for. The record
contains the access and refresh tokens, your issuer and subject, and timestamps. It never contains your email.

| Store | Status |
|---|---|
| macOS Keychain | Supported. Verified with a real Keychain on macOS 27.0.1. |
| Linux Secret Service (for example GNOME Keyring) | Supported. Verified with GNOME Keyring 48 on Debian 13; a locked keyring is refused before sign-in. |
| Windows Credential Manager | **Not supported for persistent sessions yet.** A credential holds 2,560 bytes and the store writes UTF-16; a realistic session is about 3,400 bytes, so saving it fails after you have signed in. Use `--ephemeral-auth`. |

Any other keyring backend, including plaintext and "null" backends, is refused; there is no file fallback. A locked
store is detected before the browser opens: unlock it and run the command again.

Small, non-secret lock and generation files live in your user state directory under `compose-api/sessions`
(`~/Library/Application Support/compose-api/sessions` on macOS, `~/.local/state/compose-api/sessions` on Linux). They
let several commands share one session safely. Do not delete them to reset a session; use `auth logout --local-only`.

```bash
compose-api auth status            # what is stored; contacts nothing
compose-api auth status --verify   # renews if needed and asks the API to confirm the identity
compose-api auth logout            # revokes the refresh token with Auth0, then erases the session here
compose-api auth logout --local-only
```

`auth status` without `--verify` reads only the stored record. It reports the API's confirmation as the time it was
last recorded, not as a fact about now. It exits 3 when there is no session or it has expired.

Access tokens last 24 hours. The CLI renews them a minute before they expire, using a refresh token that Auth0 rotates
on every use and that expires after 7 days unused or 30 days in total. Several commands running at once share one
renewal. If a renewal's outcome is uncertain (the network fails after the refresh token was sent), the session is
discarded rather than risking a reused token, and you sign in again.

`auth logout` cannot recall an access token already issued: it stays valid until it expires. It also leaves you signed
in to Auth0 and Google in your browser. It exits 5 if Auth0 could not be reached to revoke the refresh token (the local
session is erased anyway) and 6 if the local session could not be erased.

## Use the API

```bash
compose-api simulators list
compose-api simulations status 123
compose-api simulations submit experiment.omex --interval-time 2.5 --batch
```

Every command needs a session. Without one it exits 3: it never falls back to an anonymous request and never starts a
sign-in by itself. `--json` prints the API's own response object instead of a summary.

`submit` uploads an existing OMEX archive (a ZIP file) and prints the server's reference to the new run; it does not
wait for the simulation. It is never sent twice. If the connection fails after sending, or the server answers 500,
the run may or may not exist: check before submitting again.

When the API rejects the credentials of a read (HTTP 401), the CLI renews the session once and retries once. A 403 is
final; signing in again will not change it.

### Without a credential store

On a host where no supported store is available, add `--ephemeral-auth` to an API command:

```bash
compose-api simulators list --ephemeral-auth --device
```

The command signs in for itself, requests no refresh token, keeps the session in memory and forgets it when it
ends.

## Output and exit status

Results go to stdout; progress, prompts and errors go to stderr. With `--json`, an error is also printed to stdout as
`{"error": {"category": ..., "message": ..., "exit_code": ...}}`. Messages never contain a token, a server response
body or a configured value.

| Exit | Category | Meaning |
|---|---|---|
| 0 | | Success |
| 1 | `not_found`, `invalid_request`, `server_error`, `api_error`, `internal` | The API answered unsuccessfully (404, 400/422, 500, other), or the CLI hit a bug (`internal`, reported by type only) |
| 2 | `usage` | A malformed command line, or a file argument that cannot be used |
| 3 | `authentication` | No session, an expired one that cannot be renewed, a refused or cancelled sign-in, or credentials the API rejected |
| 4 | `forbidden` | The API refused the request for this account (403) |
| 5 | `network`, `rate_limited` | Auth0 or the API could not be reached, timed out, is unavailable (502/503/504), or is rate limiting (429) |
| 6 | `configuration`, `storage`, `protocol`, `interaction` | A profile, credential-store, protocol or local-browser problem |
| 130 | | Cancelled (Ctrl-C) |

## Troubleshooting

| Message or symptom | What to do |
|---|---|
| `cannot listen on 127.0.0.1:8400` | Another program holds the callback port. Free it, or use `--device`. The CLI never picks another port, because Auth0 only redirects to the registered one. |
| `no browser could be opened` | Use `--no-browser` and open the link yourself, or `--device`. |
| `Unsupported OS credential backend` | No supported store was found. Install or unlock one, or use `--ephemeral-auth`. |
| `OS credential store is locked` | Unlock your keychain or keyring and run the command again. |
| `Corrupt ... credential record` or `Stale credential state` | Run `compose-api auth logout --local-only`, then sign in again. |
| `the API rejected this session's credentials even after renewing the session` | The profile's `auth0_domain` or `auth0_audience` does not match what the server expects. Compare `compose-api config show` with the server's `AUTH0_DOMAIN`/`AUTH0_AUDIENCE`. |
| `the API has no GET /auth/me (HTTP 404)` | The server predates the identity endpoint (production, today). Your session is saved but cannot be confirmed until the server is updated. |
| `it is not valid yet` / `it has expired; check that this computer's clock is correct` | Synchronise the system clock. |
| `the sign-in code expired` | Device codes last a few minutes. Run the command again for a new one. |
| `auth0_client_id is not set for profile` | A custom profile needs `auth0_client_id`. |

## Operating the tenant

The Auth0 side is managed in the `auth0-pulumi` repository: its `compose-api` stack defines the two native
applications and its `CLI_SETUP.md` records how they were deployed and verified. The essentials:

- Two public native applications (production and local): no client secret, token endpoint authentication `none`,
  grants for authorization code with PKCE, refresh token and device code only, and the single callback
  `http://127.0.0.1:8400/callback`.
- Each application has one user grant to its own API audience, with no custom scopes and no machine or Management API
  grant. Both APIs allow offline access; refresh tokens rotate, with a 30-day absolute and 7-day idle lifetime.
- The shared `Username-Password-Authentication` and `google-oauth2` connections are enabled for both applications
  without replacing their other applications.
- New users receive the `user` role from the tenant's "BioSim Roles" post-login Action, owned by the
  `biosim-platform` stack. If the assignment fails, the Action logs `BioSim Roles: membership_pending
  <category>`, still puts `user` in the token, and retries at the next sign-in. The API derives `user` for every
  verified caller on its own, so a token's role claim is not proof that tenant membership was saved. Check
  membership with Auth0's admin tools; the CLI never calls the Management API.

## Release status

Verified on 2026-10-07:

- **Automated:** the full CLI test suite on macOS with Python 3.14 and 3.13, against the real FastAPI app with real
  signed tokens. Every exit code and failure path in the table above is covered.
- **Credential stores:** real macOS Keychain and Linux Secret Service round trips, and a locked keyring refused before
  sign-in.
- **Tenant:** the live tenant accepts both profiles' client IDs, audiences and callbacks for browser and device
  sign-in. Hosted email sign-up and sign-in, Google sign-in, refresh rotation, revocation and role assignment were
  verified live on 2026-10-06 (`auth0-pulumi`, `CLI_SETUP.md`), except a brand-new Google account's first browser
  sign-in.

Still open before production use:

- Deploy `GET /auth/me` to production (it returns 404 there today).
- Run the full sign-up → API → sign-out journey with this CLI against a deployed server, for a new and a returning
  email account and Google account, in both browser and device modes.
- Windows: store sessions within the 2,560-byte credential limit, then verify on a real Windows machine.
- Publish the package where `uv tool install compose-api` can find it.
- A first PKCE sign-in by a brand-new Google account.
- Turn on the email provider for real delivery.
- Decide on MFA and breached-password detection; both are currently off.
