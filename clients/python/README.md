# compose-api-client

The Python client for [compose-api](https://github.com/biosimulations/compose-api).

- `compose_api_client` (`api/`, `models/`, `client.py`, `types.py`, `errors.py`): **generated** from the service's
  OpenAPI spec by `make clients` in the repository root. Never edit these by hand; `make check-clients` fails on drift.
- `compose_api_client.utils.run_simulation_and_wait`: the hand-written helper pbest uses (kept from 0.2.0).

Until 0.2.0 this package lived in [biosimulations/compose-api-client](https://github.com/biosimulations/compose-api-client);
it was brought here with its history. The plan for this package, its application layer and the `compose-api` command
line is [`docs/plan-cli.md`](../../docs/plan-cli.md).
