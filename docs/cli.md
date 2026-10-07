# The `compose-api` command line

`compose-api` drives the compose-api service from a terminal or a script: submit simulations, wait for them, fetch
their results, and inspect what the service has registered. It covers every operation in the API (a test fails if
an operation is added without a command). How it is built and why: [plan-cli.md](plan-cli.md).

## Install

```console
$ pip install 'compose-api-client[cli]'      # or: uv tool install 'compose-api-client[cli]'
$ compose-api --help
```

The base package (`pip install compose-api-client`) is the Python client alone: httpx and attrs, no server
dependencies. In this repository, `uv run compose-api ...` works with no install.

## Connect

| Setting | Option | Environment | Default |
|---|---|---|---|
| Service | `--url` | `COMPOSE_API_URL` | `https://compose.cam.uchc.edu` |
| HTTP timeout | `--timeout` | `COMPOSE_API_TIMEOUT` | 300 s |
| Output | `-o/--output auto\|table\|json` | `COMPOSE_API_OUTPUT` | `auto`: a table on a terminal, JSON when piped |
| Token | `--token` | `COMPOSE_API_TOKEN` | none (the service has no auth yet) |

Global options go before the command: `compose-api -o json status 4192`. Results go to stdout; progress lines and
errors go to stderr, so `compose-api -o json ... | jq` always sees clean JSON.

## A run, start to finish

```console
$ compose-api run experiment.omex --simulator viva-pde-particle --wait --download out/ --extract
submitted simulation 4195
    0s simulation 4195: submitting
    5s simulation 4195: running (slurm 4137519)
   31s simulation 4195: completed (slurm 4137519)
{ "simulation_id": 4195, "status": "completed", ..., "files": ["out/results_2026-10-07#08-24-19.pber"] }
```

Or in steps:

```console
$ compose-api run experiment.omex --simulator viva-pde-particle     # prints simulation_database_id
$ compose-api status 4195                                            # "submitting" until the SLURM job exists
$ compose-api wait 4195
$ compose-api results 4195 --extract out/
```

- `--simulator` names a prebuilt simulator image the service is configured with. Without it, the service builds one
  from the document's dependencies, and `build-status <simulator_database_id>` follows that build.
- `status` takes several ids and asks for them in one call.
- `curated copasi` and `curated tellurium` run an SBML model with those simulators.
- `simulators list`, `processes list` and `steps list` show what is registered.
- `openapi --diff` reports whether this client and the live service disagree on the API.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success; with `--wait`, the job completed |
| 1 | The job ended failed, timed out, out of memory or cancelled (or `openapi --diff` found skew) |
| 2 | Usage error (a bad option, a missing file) |
| 3 | The service rejected the request or failed (the reason and any document violations are printed) |
| 4 | Not found (an unknown id, or results that do not exist yet) |
| 5 | `--wait-timeout` passed before the job finished |
| 130 | Interrupted |

So `compose-api run x.omex --wait && next-step` runs `next-step` only if the simulation completed.

## From Python

The command line is a thin layer over `compose_api_client.ext`, which applications can use directly:

```python
from compose_api_client.ext import ComposeSession

with ComposeSession() as s:  # https://compose.cam.uchc.edu
    sim, state, files = s.run_and_wait("experiment.omex", simulator="viva-pde-particle", dest="out/", extract=True)
```

`AsyncComposeSession` has the same methods as coroutines, and `AsyncComposeSession.in_process(app)` runs against a
FastAPI app in a test with no network.

<!-- BEGIN generated reference: `make cli-docs` rewrites everything below this line -->

# Command reference

Drive compose-api: submit simulations, wait for them, fetch results, inspect the catalogue.

**Usage**:

```console
$ compose-api [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--url TEXT`: Service base URL.  [env var: COMPOSE_API_URL; default: https://compose.cam.uchc.edu]
* `--timeout FLOAT`: HTTP timeout, seconds.  [env var: COMPOSE_API_TIMEOUT; default: 300.0]
* `-o, --output [auto|table|json]`: auto: table on a terminal, else json.  [env var: COMPOSE_API_OUTPUT; default: auto]
* `--token TEXT`: Bearer token (when auth is on).  [env var: COMPOSE_API_TOKEN]
* `-v, --verbose`: Log HTTP requests; tracebacks on errors.
* `-q, --quiet`: No progress lines.
* `--install-completion`: Install completion for the current shell.
* `--show-completion`: Show completion for the current shell, to copy it or customize the installation.
* `--help`: Show this message and exit.

**Commands**:

* `health`: Is the service up, and which version.
* `version`: The service's version.
* `run`: Submit a simulation.
* `status`: Job state of one simulation, or of several...
* `wait`: Wait until each simulation finishes; exit...
* `results`: Fetch a finished simulation's results...
* `build-status`: State of a simulator's container build.
* `openapi`: The OpenAPI document: this client's...
* `simulators`: Registered simulator versions.
* `processes`: Registered process-bigraph processes.
* `steps`: Registered process-bigraph steps.
* `curated`: Run an SBML model with a curated simulator.

## `compose-api health`

Is the service up, and which version.

**Usage**:

```console
$ compose-api health [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `compose-api version`

The service's version.

**Usage**:

```console
$ compose-api version [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `compose-api run`

Submit a simulation. Prints its ids; with --wait, its final state (and the files, with --download).

**Usage**:

```console
$ compose-api run [OPTIONS] DOCUMENT
```

**Arguments**:

* `DOCUMENT`: The .omex (or .pbg) to run.  [required]

**Options**:

* `--simulator TEXT`: A prebuilt simulator image by name.
* `--interval FLOAT`: Simulation interval passed to the runner.  [default: 1.0]
* `--batch / --no-batch`: Submit as a batch job (smaller partition, 1 CPU).  [default: no-batch]
* `-w, --wait`: Wait for the job to finish; exit 1 unless it completed.
* `-d, --download PATH`: With --wait: save the results archive into this directory.
* `--extract / --no-extract`: With --download: unpack the archive instead of saving the zip.  [default: no-extract]
* `--poll FLOAT`: Seconds between status checks.  [default: 5.0]
* `--wait-timeout FLOAT`: Give up waiting after this many seconds (exit 5).
* `--help`: Show this message and exit.

## `compose-api status`

Job state of one simulation, or of several in one call. &quot;submitting&quot; means no SLURM job yet.

**Usage**:

```console
$ compose-api status [OPTIONS] SIMULATION_IDS...
```

**Arguments**:

* `SIMULATION_IDS...`: One or more simulation ids.  [required]

**Options**:

* `--help`: Show this message and exit.

## `compose-api wait`

Wait until each simulation finishes; exit 1 unless all completed.

**Usage**:

```console
$ compose-api wait [OPTIONS] SIMULATION_IDS...
```

**Arguments**:

* `SIMULATION_IDS...`: One or more simulation ids.  [required]

**Options**:

* `--poll FLOAT`: Seconds between status checks.  [default: 5.0]
* `--wait-timeout FLOAT`: Give up waiting after this many seconds (exit 5).
* `--help`: Show this message and exit.

## `compose-api results`

Fetch a finished simulation's results archive.

**Usage**:

```console
$ compose-api results [OPTIONS] SIMULATION_ID
```

**Arguments**:

* `SIMULATION_ID`: The simulation id.  [required]

**Options**:

* `-O, --out PATH`: Write the zip here (a file, or a directory).
* `--extract PATH`: Unpack the archive into this directory instead.
* `--help`: Show this message and exit.

## `compose-api build-status`

State of a simulator's container build.

**Usage**:

```console
$ compose-api build-status [OPTIONS] SIMULATOR_ID
```

**Arguments**:

* `SIMULATOR_ID`: The simulator id (from a submission's simulator_database_id).  [required]

**Options**:

* `-w, --wait`: Wait for the job to finish; exit 1 unless it completed.
* `--poll FLOAT`: Seconds between status checks.  [default: 5.0]
* `--wait-timeout FLOAT`: Give up waiting after this many seconds (exit 5).
* `--help`: Show this message and exit.

## `compose-api openapi`

The OpenAPI document: this client's (default) or the service's; --diff reports skew between them.

**Usage**:

```console
$ compose-api openapi [OPTIONS]
```

**Options**:

* `--server / --no-server`: Fetch the live service's /openapi.json instead.  [default: no-server]
* `--diff / --no-diff`: Compare this client's operations with the live service's; exit 1 on skew.  [default: no-diff]
* `--help`: Show this message and exit.

## `compose-api simulators`

Registered simulator versions.

**Usage**:

```console
$ compose-api simulators [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: Simulator versions: id, definition hash,...

### `compose-api simulators list`

Simulator versions: id, definition hash, base image, creation time.

**Usage**:

```console
$ compose-api simulators list [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `compose-api processes`

Registered process-bigraph processes.

**Usage**:

```console
$ compose-api processes [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: Registered processes.

### `compose-api processes list`

Registered processes.

**Usage**:

```console
$ compose-api processes list [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `compose-api steps`

Registered process-bigraph steps.

**Usage**:

```console
$ compose-api steps [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: Registered steps.

### `compose-api steps list`

Registered steps.

**Usage**:

```console
$ compose-api steps list [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `compose-api curated`

Run an SBML model with a curated simulator.

**Usage**:

```console
$ compose-api curated [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `copasi`: Run an SBML model with COPASI.
* `tellurium`: Run an SBML model with Tellurium.

### `compose-api curated copasi`

Run an SBML model with COPASI.

**Usage**:

```console
$ compose-api curated copasi [OPTIONS] SBML
```

**Arguments**:

* `SBML`: The SBML model.  [required]

**Options**:

* `--start FLOAT`: Start time.  [required]
* `--duration FLOAT`: Duration.  [required]
* `--points INTEGER`: Number of output points.  [required]
* `-w, --wait`: Wait for the job to finish; exit 1 unless it completed.
* `-d, --download PATH`: With --wait: save the results archive into this directory.
* `--extract / --no-extract`: With --download: unpack the archive instead of saving the zip.  [default: no-extract]
* `--poll FLOAT`: Seconds between status checks.  [default: 5.0]
* `--wait-timeout FLOAT`: Give up waiting after this many seconds (exit 5).
* `--help`: Show this message and exit.

### `compose-api curated tellurium`

Run an SBML model with Tellurium.

**Usage**:

```console
$ compose-api curated tellurium [OPTIONS] SBML
```

**Arguments**:

* `SBML`: The SBML model.  [required]

**Options**:

* `--start FLOAT`: Start time.  [required]
* `--end FLOAT`: End time.  [required]
* `--points INTEGER`: Number of output points.  [required]
* `-w, --wait`: Wait for the job to finish; exit 1 unless it completed.
* `-d, --download PATH`: With --wait: save the results archive into this directory.
* `--extract / --no-extract`: With --download: unpack the archive instead of saving the zip.  [default: no-extract]
* `--poll FLOAT`: Seconds between status checks.  [default: 5.0]
* `--wait-timeout FLOAT`: Give up waiting after this many seconds (exit 5).
* `--help`: Show this message and exit.
