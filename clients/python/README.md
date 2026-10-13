# compose-api-client

The Python client for [compose-api](https://github.com/biosimulations/compose-api).

- `compose_api_client` (`api/`, `models/`, `client.py`, `types.py`, `errors.py`, `openapi.json`): **generated** from the
  service's OpenAPI spec by `make clients` in the repository root. Never edit these by hand; `make check-clients` fails
  on drift.
- `compose_api_client.ext` (`session.py`, `credentials.py`, `_policy.py`, `errors.py`): hand-written application layer
  (`ComposeSession`, `AsyncComposeSession`, `TokenSource`, destination guard, 1-renewal read replay on 401, typed
  `ExitCode` / `CliError` hierarchy). Base package dependencies only (`attrs`, `httpx`, `python-dateutil`).
- `compose_api_client.auth` and `compose_api_client.profiles` (`compose-api-client[auth]`): Auth0 OAuth 2.0 / OIDC
  client (browser PKCE and RFC 8628 device flow), OS-keychain `CredentialStore`, journaled `AuthSession` renewal and
  revocation, and profile resolution (`BUILTIN_PROFILES`, `COMPOSE_API_CLI_*`, `config.toml`).
- `compose_api_client.cli` (`compose-api-client[cli]`): the `compose-api` command-line client.
- `compose_api_client.utils.run_simulation_and_wait`: the hand-written helper pbest uses (kept from 0.2.0).

Until 0.2.0 this package lived in [biosimulations/compose-api-client](https://github.com/biosimulations/compose-api-client);
it was brought here with its history. See [`docs/cli.md`](../../docs/cli.md) and [`docs/plan-cli.md`](../../docs/plan-cli.md).
