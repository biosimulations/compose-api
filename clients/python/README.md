# compose-api-client

The Python client for [compose-api](https://github.com/biosimulations/compose-api).

- `compose_api_client` (`api/`, `models/`, `client.py`, `types.py`, `errors.py`): **generated** from the service's
  OpenAPI spec by `make clients` in the repository root. Never edit these by hand; `make check-clients` fails on drift.
- `compose_api_client.utils.run_simulation_and_wait`: the hand-written helper pbest uses (kept from 0.2.0).
- `compose_api_client.cli`: the `compose-api` command (`pip install 'compose-api-client[cli]'`). Its Auth0 login
  (`cli/auth.py`) follows VCell's `vcell_client/auth/auth_utils.py`; the base install does not depend on it.

Until 0.2.0 this package lived in [biosimulations/compose-api-client](https://github.com/biosimulations/compose-api-client);
it was brought here with its history. The plan for this package, its application layer and the `compose-api` command
line is [`docs/plan-cli.md`](../../docs/plan-cli.md).

CLI login/signup reuse the [BioSimulations portal](https://biosim.biosimulations.org/login); login then requires
a separate native PKCE authorization and Compose API confirmation. `compose-api auth login` stores the confirmed
tokens in `~/.compose-api/tokens.json` (directory 0700, file 0600, keyed by API URL; POSIX only, use `--token`
elsewhere). See the [CLI guide](../../docs/cli.md) for expiry, renewal, logout, and production deployment limitations.
