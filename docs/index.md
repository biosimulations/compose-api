# compose-api

[![Release](https://img.shields.io/github/v/release/biosimulations/compose-api)](https://img.shields.io/github/v/release/biosimulations/compose-api)
[![Build status](https://img.shields.io/github/actions/workflow/status/biosimulations/compose-api/main.yml?branch=main)](https://github.com/biosimulations/compose-api/actions/workflows/main.yml?query=branch%3Amain)
[![Commit activity](https://img.shields.io/github/commit-activity/m/biosimulations/compose-api)](https://img.shields.io/github/commit-activity/m/biosimulations/compose-api)
[![License](https://img.shields.io/github/license/biosimulations/compose-api)](https://img.shields.io/github/license/biosimulations/compose-api)

An API server for reproducible biological workflows and cosimulations.

## Authentication

Optional. Omitting `Authorization` leaves the request anonymous. A bad bearer token is `401`, not an anonymous
call. `GET /health` and `GET /version` ignore the header. A valid access token identifies the caller and does not
make a simulation private.

How to obtain an access token, which audience to use, and what not to send: [Authentication](authentication.md).

## Command-line client

`compose-api` signs you in through Auth0 and calls this API from a terminal: the simulator catalog, a
simulation's status, and new submissions. Installation, profiles, sessions and exit codes:
[Command-line client](cli.md).
