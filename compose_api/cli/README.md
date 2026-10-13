# Compose API Command-Line Interface (`compose_api.cli`)

This package implements `compose-api`, a standalone, native command-line client for the Compose API. It provides secure human authentication through Auth0, credential storage in approved OS credential managers, session lifecycle management with serialized token rotation, and typed interaction with the Compose API via generated client bindings.

---

## Architecture Overview

```mermaid
graph TD
    User([User / Shell]) --> CLI[compose-api CLI Entry: main.py]
    CLI --> Config[Profile & Config: config.py]
    CLI --> CmdAuth[commands/auth.py]
    CLI --> CmdAPI[commands/api.py]

    CmdAuth --> SignIn[auth/signin.py]
    SignIn --> BrowserPKCE[auth/browser.py + callback.py]
    SignIn --> DeviceFlow[auth/device.py]
    SignIn --> OAuth[auth/oauth.py: Auth0OAuthClient]

    CmdAuth --> Session[auth/session.py: AuthSession]
    Session --> Store[auth/storage.py: KeyringCredentialStore]
    Session --> LockState[auth/state.py: portalocker + journal]

    CmdAPI --> ComposeApi[api.py: ComposeApi]
    ComposeApi --> Session
    ComposeApi --> GenClient[api/client: AuthenticatedClient]
    GenClient --> RemoteAPI([Compose API Server])
```

### Core Design Principles

1. **Lightweight & Isolated Execution:**
   - The CLI does not load FastAPI, SQLAlchemy, HPC services, or server configuration `.env` files.
   - Help (`--help`) and configuration inspection run completely offline without importing heavy dependencies.
2. **Zero Plaintext Credential Exposure:**
   - No passwords or tokens are accepted via command-line arguments or environment variables.
   - No tokens are dumped to `stdout`, `stderr`, or logs.
   - Sessions are persisted exclusively in approved OS-level credential stores (or kept in memory for ephemeral invocations).
3. **Strict Origin & Token Boundary:**
   - Access tokens (targeted to the Compose API audience) are never sent to Auth0 or third-party hosts.
   - ID tokens (targeted to the native client ID) and refresh tokens are never sent to the Compose API.
   - Generated client calls pass through request hooks that enforce exact destination scheme, host, port, and allowed paths.
4. **Crash-Safe Serialized Concurrency:**
   - Cross-process file locking via `portalocker` ensures only one process performs token refresh at a time.
   - An in-flight journal prevents replay of spent refresh tokens if a process crashes mid-refresh.

---

## Directory Structure

```text
compose_api/cli/
├── __init__.py          # Package initialization
├── __main__.py          # Entry point for `python -m compose_api.cli`
├── main.py              # Argparse command tree, exit code mapping, asyncio runner
├── config.py            # CliSettings, TOML loader, origin validation, profile digest
├── errors.py            # Exception hierarchy (CliError) and exit code mapping
├── output.py            # Output sanitization, control-character escaping, JSON formatting
├── api.py               # ComposeApi wrapper around generated client, status classification
├── commands/
│   ├── __init__.py
│   ├── common.py        # Dependency injection / Wiring container for test isolation
│   ├── auth.py          # Handlers for `signup`, `login`, `status`, `logout`
│   └── api.py           # Handlers for `simulators list`, `simulations status/submit`
└── auth/
    ├── __init__.py
    ├── models.py        # Pydantic models (Identity, SessionRecord, AuthTransaction)
    ├── oauth.py         # Auth0OAuthClient: discovery, PKCE, token validation, JWKS
    ├── browser.py       # External system browser launcher
    ├── callback.py      # Loopback HTTP server (127.0.0.1:8400) for PKCE callbacks
    ├── device.py        # RFC 8628 Device Authorization Flow state machine
    ├── signin.py        # Sign-in coordination (browser PKCE vs. device code)
    ├── storage.py       # CredentialStore protocol, KeyringCredentialStore, MemoryCredentialStore
    ├── session.py       # AuthSession: token access, proactive renewal, generation tracking
    ├── state.py         # Process locking, permissions (0700/0600), refresh journal
    └── windows_state.py # Windows ACL and native credential replacement utilities
```

---

## Module Breakdown

### 1. Command Tree & Execution (`main.py`, `output.py`)
- Standard-library `argparse` hierarchy defining `config`, `auth`, `simulators`, and `simulations`.
- Standardized exit codes:
  - `0`: Success.
  - `1`: API error (404, 400/422, 500) or internal bug.
  - `2`: Usage error (invalid arguments, invalid file format).
  - `3`: Authentication required or expired session.
  - `4`: Forbidden (HTTP 403).
  - `5`: Network failure, rate limit (429), or server outage (502/503/504).
  - `6`: Configuration, credential storage, or protocol error.
  - `130`: Interrupted (Ctrl-C).
- `output.py` ensures all terminal output escapes ASCII/ANSI control characters and formats structured JSON errors under `--json`.

### 2. Configuration & Profiles (`config.py`)
- `CliSettings` loads configuration with strict precedence:
  1. Command-line flags (`--profile`).
  2. Environment variables (`COMPOSE_API_CLI_*`).
  3. User configuration file: `config.toml` in the system config directory (`platformdirs.user_config_dir("compose-api")`).
  4. Built-in profile defaults (`production`, `local`).
- Profile bindings calculate a SHA-256 digest over `(issuer, client_id, audience, api_base_url, scopes)`. This isolates stored credentials across environments.

### 3. Authentication & OAuth (`auth/oauth.py`, `auth/models.py`)
- **Transport:** Dedicated `httpx.AsyncClient` with TLS verification, timeouts (5s connect, 15s read), and redirects disabled.
- **Protocol Helpers:** Uses Authlib protocol primitives (`prepare_grant_uri`, `create_s256_code_challenge`, `CodeIDToken`).
- **Validation:**
  - **Access Tokens:** Validated using PyJWT with RS256, strict issuer and audience checks, finite positive expiration, and 60-second leeway.
  - **ID Tokens:** Validated against the client ID audience, correct issuer, and code flow `nonce`.
  - **JWKS Management:** Keys fetched strictly from configured Auth0 tenant discovery endpoints, cached with a 30-second backoff between refetches on unknown key IDs (`kid`).

### 4. Interactive & Headless Flows (`auth/signin.py`, `auth/callback.py`, `auth/device.py`)
- **Browser PKCE (`auth/callback.py`, `auth/browser.py`):**
  - Binds a loopback TCP listener on `127.0.0.1:8400` *before* opening the system browser.
  - Generates cryptographically secure `state`, `verifier`, and `nonce`.
  - Validates exact HTTP Host, path (`/callback`), state, and query length limits (8 KiB).
  - Emits static HTML responses with restrictive CSP (`default-src 'none'`) and `Cache-Control: no-store`.
- **Device Authorization Flow (`auth/device.py`):**
  - RFC 8628 implementation for headless or SSH sessions via `--device`.
  - Displays verification URL and short user code; device code is kept strictly in memory.
  - Handles polling intervals, exponential backoff on `slow_down`, and terminal states (`expired_token`, `access_denied`).
- **Ephemeral Sessions:**
  - Invoked with `--ephemeral-auth` on API commands.
  - Holds tokens exclusively in `MemoryCredentialStore`, omits `offline_access` scope, and discards tokens when the command process exits.

### 5. Credential Persistence & Concurrency (`auth/storage.py`, `auth/session.py`, `auth/state.py`)
- **Store Allowlist:** Only verified OS credential managers are permitted (`KeyringCredentialStore`):
  - macOS Keychain (`keyring.backends.macOS.Keyring`).
  - Linux Secret Service (`keyring.backends.SecretService.Keyring`).
  - Windows Credential Manager (`keyring.backends.Windows.WinVaultKeyring`).
  - Insecure or plaintext fallbacks (e.g., `keyrings.alt`) are explicitly rejected.
- **Atomic Concurrency & Journaling:**
  - State directory files are locked via `portalocker` (30s deadline).
  - POSIX directory permissions are enforced to `0700` and state files to `0600` with file owner validation.
  - Refresh rotation writes an `in_flight` journal entry containing the transaction ID before transmitting the refresh token. If interrupted or crashed, old refresh tokens are never replayed.
  - A generation counter detects concurrent token replacement or logout races.

### 6. API Integration Boundary (`api.py`, `commands/api.py`)
- Wraps generated client operations (`api/client`) inside `ComposeApi`.
- Request hooks guard against credential leakage:
  - Validates destination scheme, host, and port against `api_base_url`.
  - Disallows userinfo, queries, or redirects with credentials.
  - Restricts paths to allowlisted endpoints (`/auth/me`, `/core/simulator/list`, `/results/simulation/status`, `/simulation/run`).
- Automatic retry on 401:
  - Read operations (`simulators list`, `simulations status`) perform at most one proactive token refresh and one replay.
  - Mutation operations (`simulations submit`) **never** replay automatically on 401, timeout, or 5xx to prevent duplicate simulation runs.
- Identity Confirmation:
  - After sign-in, the CLI calls `GET /auth/me` to verify server recognition before reporting success.

---

## Running the CLI from a Checkout

From the repository root, use the project environment:

```bash
uv run compose-api --help
uv run python -m compose_api.cli --help   # Equivalent entry point
```

If the bare `compose-api` command reports `zsh: command not found`, use `uv run compose-api`
for the examples below. Alternatively, activate the environment first:

```bash
source .venv/bin/activate
compose-api --help
```

The repeated `Uninstalled 1 package` / `Installed 1 package` messages seen during local runs
come from `uv` synchronizing the environment (observed here for `antimony`). They do not
indicate an authentication or API connection failure.

### Local Server and PostgreSQL Setup

The CLI is a client: it does not start the API, PostgreSQL, or a simulation runner.
Configure the server using `assets/dev/config/.dev_env_TEMPLATE` as a starting point for
`assets/dev/config/.dev_env`. If `.dev_env` already exists, edit it while preserving its
existing settings.

PostgreSQL must be running at `POSTGRES_HOST` and `POSTGRES_PORT`, with the configured
`POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DATABASE`. If the existing local
database container is named `compose-api-postgres`, start it with:

```bash
docker start compose-api-postgres
```

This command starts an existing container; it does not create a database container.
A startup traceback ending in `Connect call failed` for `::1:5432` and `127.0.0.1:5432`
means PostgreSQL is unreachable. The API cannot finish startup or serve requests on
port 8000 until the database connection succeeds.

For the local Auth0 application, set these **server** values in `.dev_env`:

```dotenv
AUTH0_DOMAIN=dev-bu7yo7484tyxu6a1.us.auth0.com
AUTH0_AUDIENCE=https://api.compose.local
```

Start the API in one terminal and wait for `Application startup complete`:

```bash
make run
```

In another terminal, choose the local CLI profile and override its built-in cluster URL
to use the development server:

```bash
export COMPOSE_API_CLI_PROFILE=local
export COMPOSE_API_CLI_API_BASE_URL=http://localhost:8000
uv run compose-api config show
uv run compose-api auth login
```

The built-in `local` profile uses audience `https://api.compose.local` and native client ID
`Fp3QmULWNIhdutlBRVFm2HjPGapqdnKV`. Its default API URL is `https://api.compose-api-local`,
so the loopback URL override above is needed for `make run`.

Check `config show` for pre-existing `COMPOSE_API_CLI_AUTH0_AUDIENCE` and
`COMPOSE_API_CLI_AUTH0_CLIENT_ID` overrides. The audience must match the server's
`AUTH0_AUDIENCE`, and the client ID must identify the corresponding native application.
Selecting a profile does not override explicit setting environment variables. A profile
shown as `production` can therefore still point at localhost when environment overrides
are present.

The CLI does not read the server's `.dev_env`. Restart the API after changing that file.
A user `config.toml` reported as `(not found)` is normal when using built-in settings and
environment variables. On macOS, that optional file lives at
`~/Library/Application Support/compose-api/config.toml`.

### Remote SLURM Configuration for Simulations

Starting PostgreSQL and the API enables database-backed requests and authentication.
Simulation execution additionally requires a configured remote SLURM backend; the server
currently has no local simulation execution path.

Configure the following server settings in `.dev_env` with your cluster's actual values:

```dotenv
SLURM_SUBMIT_HOST=<cluster-submit-host>
SLURM_SUBMIT_USER=<cluster-user>
SLURM_SUBMIT_KEY_PATH=<absolute-path-to-ssh-key>
SLURM_SUBMIT_KNOWN_HOSTS=<absolute-path-to-known-hosts>
SLURM_PARTITION=<partition>
SLURM_QOS=<cluster-qos>
SLURM_BUILD_NODE=<build-node>
SIMULATION_STORE_BASE_PATH=<writable-cluster-storage-path>
```

Replace the placeholders before restarting the API. The configured user needs SSH access,
permission to submit jobs, writable storage, and the cluster's required Apptainer/Singularity
environment. Batch submissions also use `BATCH_SLURM_PARTITION` and `BATCH_SLURM_QOS`.
Use the appropriate `NAMESPACE` for the cluster's storage subtree.

## Command Reference

The command hierarchy consists of global flags, configuration inspection, authentication lifecycle management, and API domain actions.

### Global Options

Options valid across all commands (accepted before or after the subcommand):

| Option | Description |
|---|---|
| `--profile NAME` | Selects profile: `production` (default), `local`, or a custom profile from `config.toml`. |
| `--json` | Formats stdout output as a stable JSON document. Errors emit `{"error": {"category", "message", "exit_code"}}`. |
| `--version` | Displays `compose_api` package version and exits. |
| `-h`, `--help` | Displays help message and exits (runs offline without dependencies). |

---

### Configuration Commands

#### `compose-api config show`
Prints effective configuration parameters and their provenance (defaults, `config.toml`, or environment variables).

```bash
compose-api config show
compose-api config show --profile local
compose-api config show --json
```

---

### Authentication Commands (`compose-api auth`)

#### `compose-api auth signup`
Initiates sign-up on Auth0 hosted pages, completes S256 PKCE exchange (or Device Flow), stores credentials in OS credential manager, and confirms identity with `GET /auth/me`.

```bash
compose-api auth signup                     # Hosted email/password signup
compose-api auth signup --provider google   # First-time Google social authentication
compose-api auth signup --device            # Headless / SSH device authorization flow
compose-api auth signup --no-browser        # Print authorization URL instead of launching browser
```

#### `compose-api auth login`
Initiates sign-in for returning users via Auth0 Universal Login, stores tokens in OS credential manager, and confirms identity with `GET /auth/me`.

```bash
compose-api auth login
compose-api auth login --provider email
compose-api auth login --provider google
compose-api auth login --device             # RFC 8628 device flow for remote/headless terminals
compose-api auth login --no-browser
```

If login reports `signed in and saved the session, but the Compose API did not confirm it`,
Auth0 sign-in completed and the session was saved. Browser and device login both finish by
calling the API's `GET /auth/me`, so switching to `--device` does not fix an unreachable API.
Check the API URL, database availability, and server startup first, then verify the saved
session without signing in again:

```bash
uv run compose-api auth status
uv run compose-api auth status --verify
```

Keep the same effective CLI settings as the original login. Changing the issuer, client ID,
audience, API origin, or scopes selects a different session binding. When verification succeeds,
the CLI reports `API: confirmed this identity just now`. A valid local session with
`API: never confirmed` means the stored session has not yet been confirmed by the API;
a connection failure during verification does not sign you out.

#### `compose-api auth status`
Inspects stored session information. Without flags, runs offline and reads only the local OS credential store.

```bash
compose-api auth status            # Offline check: state, expiration, renewable status, last confirmed time
compose-api auth status --verify   # Online check: refreshes token if needed and re-verifies with GET /auth/me
compose-api auth status --json     # Emits structured session status
```

#### `compose-api auth logout`
Revokes the refresh token at Auth0 and deletes stored credentials and state files on the local machine.

```bash
compose-api auth logout              # Revokes refresh token at Auth0, then purges local credentials
compose-api auth logout --local-only # Skips network call and purges local credentials immediately
```

---

### API Commands

All API commands require an active session. If none is present, they exit with code `3` (`AUTH_REQUIRED`) without making network requests.

#### `compose-api simulators list`
Lists all available simulation engines registered in the API (`GET /core/simulator/list`).

```bash
compose-api simulators list
compose-api simulators list --json
```

#### `compose-api simulations status ID`
Queries the status and execution details of a simulation by its numeric ID (`GET /results/simulation/status?simulation_id=ID`).

```bash
compose-api simulations status 123
compose-api simulations status 123 --json
```

`ID` is required. Running `simulations status` without it produces an argparse usage error;
this command does not list simulations.

#### Troubleshooting: Submission Succeeds but Status Reports No Simulation

The current server saves the simulation and returns its database ID before a background task
dispatches the SLURM job. The status endpoint looks for the associated HPC job record. If
dispatch has not created that record, the CLI reports `there is no simulation ID on this server`,
even when the simulation database row exists. This can occur while preparing the simulator or
after a dispatch failure; the message alone does not establish that the simulation is missing.

For example, the local submission of `MODEL1610100004.5.omex` returned simulation 2, and the
database contained simulation 2 but no HPC job records. The server's SLURM host, username,
SSH key path, and partition were unset, leaving execution unconfigured.

To resolve this:

1. Confirm submit and status use the same effective API configuration with `uv run compose-api config show`.
2. Check the server logs for errors from the background dispatch, container download/build, or SSH connection.
3. Configure the remote backend described in [Remote SLURM Configuration for Simulations](#remote-slurm-configuration-for-simulations).
4. Restart the API. If the earlier dispatch failed, resubmit and check the newly returned ID:

   ```bash
   uv run compose-api simulations submit ~/Downloads/MODEL1610100004.5.omex
   uv run compose-api simulations status <new-id>
   ```

Restarting the API does not automatically retry the earlier submission. Verify that dispatch
failed before resubmitting, since a new submission can create a duplicate when the original
is still preparing or running. The CLI does not automatically replay submissions.

#### `compose-api simulations submit FILE`
Validates and uploads an OMEX archive (ZIP file) to execute a simulation (`POST /simulation/run`). Multipart upload is not automatically replayed on failure to protect against duplicate runs.

```bash
compose-api simulations submit experiment.omex
compose-api simulations submit experiment.omex --interval-time 2.5
compose-api simulations submit experiment.omex --batch
compose-api simulations submit experiment.omex --batch --json
```

---

### Ephemeral Mode for Headless / Container Hosts (`--ephemeral-auth`)

On environments where no supported OS credential store is available (e.g., Docker containers, minimal CI runners), API commands support `--ephemeral-auth`. This executes a one-time interactive login into process memory without storing credentials on disk or in keyrings:

```bash
compose-api simulators list --ephemeral-auth --device
compose-api simulations status 123 --ephemeral-auth --device
compose-api simulations submit model.omex --ephemeral-auth --no-browser
```
---

## Packaging and Global Installation

`compose-api` is configured as a standalone console script in `pyproject.toml`:

```toml
[project.scripts]
compose-api = "compose_api.cli.main:main"
```

When installed via an isolated tool manager like `uv tool` or `pipx`, the executable binary is placed into the user's tool bin directory (`~/.local/bin` on Linux/macOS, `%LOCALAPPDATA%\bin` on Windows). Once that directory is on `$PATH`, `compose-api` can be invoked from any directory on the computer without prefixing `uv run`.

### 1. Local Installation (For Developers / Contributors)

To install the CLI from this local checkout so that `compose-api` is available globally in your shell:

#### Editable Installation (Recommended for Development)
Links the global command directly to your working tree. Code edits take effect immediately without reinstallation:

```bash
uv tool install --editable .
```

*(For a standard non-editable install of the current working directory: `uv tool install .`)*

#### Ensure Binary Directory is on `$PATH`
If invoking `compose-api` returns `command not found`, ensure your shell includes the tool directory:

```bash
uv tool update-shell
```
Then restart your shell or reload your environment (`source ~/.zshrc` or `source ~/.bashrc`).

---

### 2. Building Distribution Artifacts (Packaging)

To package the CLI and server into standalone distribution archives (wheel `.whl` and source distribution `.tar.gz`):

```bash
uv build
```

This compiles and outputs the distribution artifacts into `dist/`:
- `dist/compose_api-0.5.0-py3-none-any.whl`
- `dist/compose_api-0.5.0.tar.gz`

---

### 3. How Other Users Can Install and Run It Globally

End users do not need to clone the git repository, install developer dependencies, or manage virtual environments manually.

#### Option A: Direct Installation via `uv tool` from Git (Recommended)
Users with `uv` installed can install directly from GitHub using a tag or branch:

```bash
# Install from a release tag
uv tool install "git+https://github.com/biosimulations/compose-api.git@<tag>"

# Install from a branch
uv tool install "git+https://github.com/biosimulations/compose-api.git@feature/cli-client"
```

#### Option B: Installation from a Built Wheel (`.whl`)
If distributing a pre-built wheel file from `dist/`:

```bash
uv tool install ./compose_api-0.5.0-py3-none-any.whl
```

#### Option C: Installation via `pipx` (For Users Without `uv`)
Users using standard Python tooling with `pipx`:

```bash
# Install from GitHub
pipx install "git+https://github.com/biosimulations/compose-api.git@<tag>"

# Or from a pre-built wheel
pipx install ./compose_api-0.5.0-py3-none-any.whl
```

#### Option D: Standard Virtual Environment (`pip`)
Inside an existing virtual environment with Python $\ge$ 3.13.2:

```bash
pip install ./compose_api-0.5.0-py3-none-any.whl
```

---

### 4. Installation Maintenance & Constraints

- **Python Floor:** Requires Python **3.13.2 or newer**. `uv tool` downloads and provisions a compliant Python runtime automatically if one is not present on the host.
- **Footprint:** The tool environment installs server scientific packages (NumPy, Polars, LibSBML) totaling $\approx 1\text{ GB}$. The CLI startup path lazy-loads modules and executes help and config commands in milliseconds without importing those scientific libraries.
- **Upgrades:** Run `uv tool upgrade compose-api` (or `pipx upgrade compose-api`).
- **Uninstallation:** Run `uv tool uninstall compose-api` (or `pipx uninstall compose-api`).

---

## Testing & Dependency Injection

The CLI is engineered for complete test isolation without requiring live networks, browser windows, or real OS keyrings during automated runs.

### The `Wiring` Container (`commands/common.py`)
Commands accept an optional `Wiring` object that overrides:
- `auth0_transport`: Injects HTTPX `MockTransport` or ASGI adapters.
- `api_transport`: Injects ASGI `ASGITransport` targeting the FastAPI `app`.
- `browser`: Injects `FakeBrowser` to intercept authorization URLs without launching a browser.
- `store`: Injects `MemoryCredentialStore` to keep tests off the host machine's real keychain.

### Test Suites (`tests/cli/`)

| Test Module | Coverage |
|---|---|
| `test_commands.py` | Parser behavior, help text, subprocess execution, exit codes. |
| `test_config.py` | Profile loading, precedence, TOML parsing, URL validation, binding hashes. |
| `test_oauth.py` | OAuth discovery, PKCE challenge generation, token verification, JWKS rotation and outages. |
| `test_browser_auth.py` | Callback listener HTTP assertions, state mismatch, timeout, browser launch failure. |
| `test_device_auth.py` | Device flow polling, backoff, expired codes, cancellation, ephemeral mode. |
| `test_storage.py` | Keyring backend allowlisting, serialization, corruption handling, locked store detection. |
| `test_session.py` | Concurrent refresh under lock, generation conflict resolution, crash-recovery journaling, logout. |
| `test_os_keyring.py` | Real macOS Keychain / Linux Secret Service opt-in integration tests (`COMPOSE_API_TEST_OS_KEYRING=1`). |
| `test_api.py` | Generated client invocation against real ASGI app, destination guard, 401 retry, multipart upload. |
| `test_errors.py` | Error matrix verification (19 scenarios), redaction, leak scanning for secrets in output/logs. |
| `test_packaging.py` | Built wheel validation, console script declarations, dependency constraints. |
| `test_documentation.py` | Markdown drift tests ensuring `docs/cli.md` documents all commands, options, and exit codes. |

---

## Quick Reference: Developer Commands

```bash
# Run all unit/contract tests for the CLI
uv run pytest tests/cli

# Run real OS Keyring test (writes and cleans up a synthetic record in host Keychain)
COMPOSE_API_TEST_OS_KEYRING=1 uv run pytest tests/cli/test_os_keyring.py

# Run linting, strict mypy type checking, and dependency checks
make check

# Build documentation and check for broken links
make docs-test

# Test local CLI commands
uv run compose-api config show
uv run compose-api auth status
```
