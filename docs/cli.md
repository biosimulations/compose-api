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
| Token | `--token` | `COMPOSE_API_TOKEN` | none: anonymous. An Auth0 access token for this API identifies you ([authentication](authentication.md)) |

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

- **Simulation ids.** A simulation id is what `run` prints (`simulation_database_id`), and what `status`, `wait`,
  `results`, `events`, `trace` and `datasets list --sim` take. To find one later:

  ```console
  $ compose-api simulations list                          # newest first, with status and SLURM job
  $ compose-api simulations list --status running --since 6h
  $ compose-api simulations list --simulator viva-pde-particle --limit 20
  $ compose-api simulations list --label source:biomodels --tag repressilator
  $ compose-api simulations show 4334                     # plus how many events and datasets it recorded
  ```

  Runs carry **labels**, written by the service (`source`, `environment`, `solver`, `model`, ...), and **tags** and a
  **description** given at submission: `compose-api run x.omex --tag demo --tag repressilator --description "..."`.
  `--label key:value` and `--tag` filter the list; each is repeatable, and all must match.

  The list shows only simulations you can read; once auth is in place, that's yours and the public ones.
- `--simulator` names a prebuilt simulator image the service is configured with. Without it, the service builds one
  from the document's dependencies, and `build-status <simulator_database_id>` follows that build.
- `status` takes several ids and asks for them in one call.
- `curated copasi` and `curated tellurium` run an SBML model with those simulators.
- `simulators list`, `processes list` and `steps list` show what is registered.
- `openapi --diff` reports whether this client and the live service disagree on the API.

## JSON output

Every command takes `--json`, which prints JSON instead of a table. It's the same as `--output json` before the
command name, and it overrides that option. JSON is also the default whenever output isn't a terminal, so
`compose-api simulations list | jq` needs neither.

## What a run did: events and traces

Every run records events: the service's own (`dispatch.submitted`, then `slurm.<state>` on each change), the job
script's (`job.start`, and `job.end` with the exit code, inside a `job` span), and, if the simulator is built on
process-bigraph 1.8.5 or later, the engine's (`run.start`, `run.end`, `process.exception`, its spans).

```console
$ compose-api events 4195                  # everything recorded so far
$ compose-api events 4195 --follow         # and new ones as they arrive, until the job has finished
$ compose-api events 4195 --level error    # only what went wrong
$ compose-api trace 4195                   # the spans as a tree, each with its own events
$ compose-api trace 4195 --chrome t.json   # a file for ui.perfetto.dev
```

With `--output json`, `events` prints JSON lines, one event per line. The service reads a run's events while it runs
and for a few minutes after it ends, so a `--follow` may print a last few events after the job is done.

## What a run produced: datasets

Each file a run leaves in its `output/` directory, and its `results.zip`, is a dataset. The job script records each
with its size and sha256 when the run ends. A simulator can announce its own files with an `artifact.written` event,
adding a kind, a name and attributes.

```console
$ compose-api datasets list --sim 4195            # one run's files
$ compose-api datasets list --kind results         # every results file you can read
$ compose-api datasets show <id>
$ compose-api datasets get <id> -O out/            # just that file, not the whole archive
```

A run's SLURM log is a dataset too (`job.out`, kind `log`): `compose-api datasets list --sim 4195 --kind log`, then
`datasets get` on its id. A dataset is readable by whoever can read its simulation.

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
* `catalog`: The catalog: every registry entry with its...
* `solvers`: The solvers SED-ML runs can use: each...
* `run`: Submit a simulation.
* `status`: Job state of one simulation, or of several...
* `wait`: Wait until each simulation finishes; exit...
* `results`: Fetch a finished simulation's results...
* `events`: A simulation's events: from the API, the...
* `trace`: A simulation's spans as a tree, each with...
* `build-status`: State of a simulator's container build.
* `openapi`: The OpenAPI document: this client's...
* `build-log`: The SLURM log of a simulator's newest...
* `simulators`: Registered simulator versions.
* `processes`: Registered process-bigraph processes.
* `steps`: Registered process-bigraph steps.
* `curated`: Run an SBML model with a curated simulator.
* `datasets`: The files runs produced.
* `simulations`: Find simulations and their ids.
* `environments`: The environments documents run in, and the...
* `sedml`: Run SED-ML archives on several solvers and...
* `comparisons`: A SED-ML task's runs on several solvers,...
* `biomodels`: EBI BioModels: search, describe, download,...
* `biosimulations`: biosimulations.org projects: search,...
* `suites`: Regression and reproducibility suites of...

## `compose-api health`

Is the service up, and which version.

**Usage**:

```console
$ compose-api health [OPTIONS]
```

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api version`

The service's version.

**Usage**:

```console
$ compose-api version [OPTIONS]
```

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api catalog`

The catalog: every registry entry with its curation level, and the environments that provide its classes.

Discovery and trust, not runnability: most `listed` entries are in no environment (docs/plan-sedml.md).

**Usage**:

```console
$ compose-api catalog [OPTIONS]
```

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api solvers`

The solvers SED-ML runs can use: each one's class, environment, KiSAO algorithms (default first).

**Usage**:

```console
$ compose-api solvers [OPTIONS]
```

**Options**:

* `--json`: Print JSON (the same as --output json).
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
* `-t, --tag TEXT`: A tag to find the run by later (repeatable).
* `--description TEXT`: What the run is for.
* `-w, --wait`: Wait for the job to finish; exit 1 unless it completed.
* `-d, --download PATH`: With --wait: save the results archive into this directory.
* `--extract / --no-extract`: With --download: unpack the archive instead of saving the zip.  [default: no-extract]
* `--poll FLOAT`: Seconds between status checks.  [default: 5.0]
* `--wait-timeout FLOAT`: Give up waiting after this many seconds (exit 5).
* `--json`: Print JSON (the same as --output json).
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

* `--json`: Print JSON (the same as --output json).
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
* `--json`: Print JSON (the same as --output json).
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
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api events`

A simulation's events: from the API, the job script and the simulator's engine. JSON output is JSON lines.

**Usage**:

```console
$ compose-api events [OPTIONS] SIMULATION_ID
```

**Arguments**:

* `SIMULATION_ID`: The simulation id.  [required]

**Options**:

* `-f, --follow`: Keep printing new events until the job has finished.
* `--level TEXT`: Only events at this level: debug, info, warning, error.
* `--event TEXT`: Only events with this name, e.g. job.end.
* `--poll FLOAT`: Seconds between status checks.  [default: 5.0]
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api trace`

A simulation's spans as a tree, each with its own events; or, with --chrome, a file for Perfetto.

**Usage**:

```console
$ compose-api trace [OPTIONS] SIMULATION_ID
```

**Arguments**:

* `SIMULATION_ID`: The simulation id.  [required]

**Options**:

* `--chrome PATH`: Save the trace as a Chrome Trace Event file instead; open it in ui.perfetto.dev.
* `--json`: Print JSON (the same as --output json).
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
* `--json`: Print JSON (the same as --output json).
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
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api build-log`

The SLURM log of a simulator's newest container build.

**Usage**:

```console
$ compose-api build-log [OPTIONS] SIMULATOR_ID
```

**Arguments**:

* `SIMULATOR_ID`: The simulator id (a run's simulator_id).  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
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
* `images`: Whether a simulator's image is built: its...
* `build`: Make a simulator's image available: pulled...

### `compose-api simulators list`

Simulator versions: id, definition hash, base image, creation time.

**Usage**:

```console
$ compose-api simulators list [OPTIONS]
```

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api simulators images`

Whether a simulator's image is built: its image records and its newest build run.

**Usage**:

```console
$ compose-api simulators images [OPTIONS] SIMULATOR_ID
```

**Arguments**:

* `SIMULATOR_ID`: The simulator's id.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api simulators build`

Make a simulator's image available: pulled or built unless it is, joining a build under way.

**Usage**:

```console
$ compose-api simulators build [OPTIONS] SIMULATOR_ID
```

**Arguments**:

* `SIMULATOR_ID`: The simulator's id.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
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

* `--json`: Print JSON (the same as --output json).
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

* `--json`: Print JSON (the same as --output json).
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
* `--json`: Print JSON (the same as --output json).
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
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api datasets`

The files runs produced.

**Usage**:

```console
$ compose-api datasets [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: The files runs produced: one simulation's,...
* `show`: Everything recorded about one dataset.
* `get`: Download a dataset's file.
* `file`: Download one file from inside a directory...

### `compose-api datasets list`

The files runs produced: one simulation's, or every one you may read, newest simulations first.

**Usage**:

```console
$ compose-api datasets list [OPTIONS]
```

**Options**:

* `--sim INTEGER`: Only this simulation's datasets.
* `--kind TEXT`: Only this kind: results, table, figure, archive, ...
* `--match TEXT`: Only paths or names containing this.
* `--missing / --no-missing`: List datasets whose file is gone instead.  [default: no-missing]
* `--limit INTEGER`: At most this many.  [default: 100]
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api datasets show`

Everything recorded about one dataset.

**Usage**:

```console
$ compose-api datasets show [OPTIONS] DATASET_ID
```

**Arguments**:

* `DATASET_ID`: The dataset id.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api datasets get`

Download a dataset's file.

**Usage**:

```console
$ compose-api datasets get [OPTIONS] DATASET_ID
```

**Arguments**:

* `DATASET_ID`: The dataset id.  [required]

**Options**:

* `-O, --out PATH`: Write it here (a file, or a directory). Default: here.
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api datasets file`

Download one file from inside a directory dataset.

**Usage**:

```console
$ compose-api datasets file [OPTIONS] DATASET_ID SUBPATH
```

**Arguments**:

* `DATASET_ID`: The dataset id (a directory dataset: a results bundle or zarr).  [required]
* `SUBPATH`: The file inside it, e.g. .zattrs or u/0.0.  [required]

**Options**:

* `-O, --out PATH`: Write it here (a file, or a directory). Default: here.
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api simulations`

Find simulations and their ids.

**Usage**:

```console
$ compose-api simulations [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: Simulations you can read, newest first,...
* `show`: One simulation: its simulator, its latest...

### `compose-api simulations list`

Simulations you can read, newest first, each with its latest SLURM job. The ids are what every other command
takes.

**Usage**:

```console
$ compose-api simulations list [OPTIONS]
```

**Options**:

* `--status TEXT`: Only this state: submitting, running, completed, failed, timeout, ...
* `--simulator TEXT`: Only this prebuilt simulator (name), or a container-definition hash prefix.
* `--since TEXT`: Only those created since: 30m, 6h, 2d, 1w, or an ISO time.
* `--label TEXT`: Only those with this label, key:value, e.g. source:biomodels (repeatable, all must match).
* `--tag TEXT`: Only those with this tag (repeatable, all must match).
* `--limit INTEGER`: At most this many.  [default: 50]
* `--offset INTEGER`: Skip this many (for the next page).  [default: 0]
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api simulations show`

One simulation: its simulator, its latest SLURM job, and how many events and datasets its run recorded.

**Usage**:

```console
$ compose-api simulations show [OPTIONS] SIMULATION_ID
```

**Arguments**:

* `SIMULATION_ID`: The simulation id.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api environments`

The environments documents run in, and the process interfaces each provides.

**Usage**:

```console
$ compose-api environments [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: Environments: the `--simulator` to run in...
* `manifest`: An environment's interface manifest: its...
* `headers`: An environment's interfaces as .pblang...
* `images`: Whether an environment's current image is...
* `build`: Make an environment's current image...

### `compose-api environments list`

Environments: the `--simulator` to run in each, its image, and whether its manifest is current.

**Usage**:

```console
$ compose-api environments list [OPTIONS]
```

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api environments manifest`

An environment's interface manifest: its steps and processes, their config schemas and ports.

`--output json` prints the manifest itself (pbg-interfaces/1), which other tools read as it is.

**Usage**:

```console
$ compose-api environments manifest [OPTIONS] NAME
```

**Arguments**:

* `NAME`: The environment, e.g. registry_env.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api environments headers`

An environment's interfaces as .pblang header files: what a composite imports (`import module.{Name};`).

Prints every module's file, or writes them into `--out`; `--output json` prints them with each class's
declaration.

**Usage**:

```console
$ compose-api environments headers [OPTIONS] NAME
```

**Arguments**:

* `NAME`: The environment, e.g. registry_env.  [required]

**Options**:

* `-o, --out PATH`: Write one &lt;module&gt;.pbl per module into this directory.
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api environments images`

Whether an environment's current image is built: its image records and its newest build run.

**Usage**:

```console
$ compose-api environments images [OPTIONS] NAME
```

**Arguments**:

* `NAME`: The environment, e.g. registry_env.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api environments build`

Make an environment's current image available: pulled or built unless it is, joining a build under way.

Returns at once; `environments images` follows the build.

**Usage**:

```console
$ compose-api environments build [OPTIONS] NAME
```

**Arguments**:

* `NAME`: The environment, e.g. registry_env.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api sedml`

Run SED-ML archives on several solvers and compare them.

**Usage**:

```console
$ compose-api sedml [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `preview`: Translate an archive without running it:...
* `run`: Run each task once per solver; prints each...

### `compose-api sedml preview`

Translate an archive without running it: its tasks, the solvers that accept each, and the findings.

**Usage**:

```console
$ compose-api sedml preview [OPTIONS] ARCHIVE
```

**Arguments**:

* `ARCHIVE`: A COMBINE/OMEX archive with SED-ML and its models.  [required]

**Options**:

* `-s, --solver TEXT`: A solver id (repeatable); all when omitted.
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api sedml run`

Run each task once per solver; prints each task's comparison and its runs.

**Usage**:

```console
$ compose-api sedml run [OPTIONS] ARCHIVE
```

**Arguments**:

* `ARCHIVE`: A COMBINE/OMEX archive with SED-ML and its models.  [required]

**Options**:

* `-s, --solver TEXT`: A solver id (repeatable); all when omitted.
* `--task TEXT`: A SED-ML task id (repeatable); all when omitted.
* `-t, --tag TEXT`: A tag for every run (repeatable).
* `--description TEXT`: What the runs are for.
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api comparisons`

A SED-ML task's runs on several solvers, and how they compare.

**Usage**:

```console
$ compose-api comparisons [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: Comparisons, newest first.
* `show`: One comparison: its runs, and per report...
* `series`: One report's columns from each run and...

### `compose-api comparisons list`

Comparisons, newest first.

**Usage**:

```console
$ compose-api comparisons list [OPTIONS]
```

**Options**:

* `--source TEXT`: Only this source, e.g. upload:x.omex.
* `--limit INTEGER`: At most this many.  [default: 25]
* `--offset INTEGER`: Skip this many.  [default: 0]
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api comparisons show`

One comparison: its runs, and per report the worst data set once every run has finished.

**Usage**:

```console
$ compose-api comparisons show [OPTIONS] COMPARISON_ID
```

**Arguments**:

* `COMPARISON_ID`: The comparison id.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api comparisons series`

One report's columns from each run and each reference (JSON; a table lists what is there).

**Usage**:

```console
$ compose-api comparisons series [OPTIONS] COMPARISON_ID
```

**Arguments**:

* `COMPARISON_ID`: The comparison id.  [required]

**Options**:

* `--report TEXT`: The SED-ML report id.  [required]
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api biomodels`

EBI BioModels: search, describe, download, run.

**Usage**:

```console
$ compose-api biomodels [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `search`: Search EBI BioModels (manually curated...
* `show`: One BioModels entry: name, curation...
* `get`: Download the entry's COMBINE archive.
* `run`: Run the entry's SED-ML once per solver;...

### `compose-api biomodels search`

Search EBI BioModels (manually curated models unless --all).

**Usage**:

```console
$ compose-api biomodels search [OPTIONS] QUERY
```

**Arguments**:

* `QUERY`: Words to search for.  [required]

**Options**:

* `--limit INTEGER`: At most this many.  [default: 20]
* `--all`: Not only manually curated models.
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api biomodels show`

One BioModels entry: name, curation status, latest revision.

**Usage**:

```console
$ compose-api biomodels show [OPTIONS] MODEL_ID
```

**Arguments**:

* `MODEL_ID`: e.g. BIOMD0000000012  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api biomodels get`

Download the entry's COMBINE archive.

**Usage**:

```console
$ compose-api biomodels get [OPTIONS] MODEL_ID
```

**Arguments**:

* `MODEL_ID`: e.g. BIOMD0000000012  [required]

**Options**:

* `-O, --out PATH`: Write the archive here (a file or a directory).
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api biomodels run`

Run the entry's SED-ML once per solver; prints each task's comparison and its runs.

**Usage**:

```console
$ compose-api biomodels run [OPTIONS] MODEL_ID
```

**Arguments**:

* `MODEL_ID`: e.g. BIOMD0000000012  [required]

**Options**:

* `-s, --solver TEXT`: A solver id (repeatable); all when omitted.
* `-t, --tag TEXT`: A tag for every run (repeatable).
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api biosimulations`

biosimulations.org projects: search, describe, download, run.

**Usage**:

```console
$ compose-api biosimulations [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `search`: biosimulations.org projects whose id...
* `show`: One project: its run and the simulator...
* `get`: Download the project's archive.
* `reference`: The project's original results: each...
* `run`: Run the project's SED-ML once per solver,...

### `compose-api biosimulations search`

biosimulations.org projects whose id contains the query.

**Usage**:

```console
$ compose-api biosimulations search [OPTIONS] [QUERY]
```

**Arguments**:

* `[QUERY]`: Part of a project id.

**Options**:

* `--limit INTEGER`: At most this many.  [default: 20]
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api biosimulations show`

One project: its run and the simulator that ran it.

**Usage**:

```console
$ compose-api biosimulations show [OPTIONS] PROJECT_ID
```

**Arguments**:

* `PROJECT_ID`: The project id.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api biosimulations get`

Download the project's archive.

**Usage**:

```console
$ compose-api biosimulations get [OPTIONS] PROJECT_ID
```

**Arguments**:

* `PROJECT_ID`: The project id.  [required]

**Options**:

* `-O, --out PATH`: Write the archive here (a file or a directory).
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api biosimulations reference`

The project's original results: each report's labels and number of points (--output json for the values).

**Usage**:

```console
$ compose-api biosimulations reference [OPTIONS] PROJECT_ID
```

**Arguments**:

* `PROJECT_ID`: The project id.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api biosimulations run`

Run the project's SED-ML once per solver, its original results as the reference.

**Usage**:

```console
$ compose-api biosimulations run [OPTIONS] PROJECT_ID
```

**Arguments**:

* `PROJECT_ID`: The project id.  [required]

**Options**:

* `-s, --solver TEXT`: A solver id (repeatable); all when omitted.
* `-t, --tag TEXT`: A tag for every run (repeatable).
* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

## `compose-api suites`

Regression and reproducibility suites of SED-ML models.

**Usage**:

```console
$ compose-api suites [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: The suites: their sources, solvers and...
* `runs`: A suite's runs, newest first.
* `show`: One suite run: per source, whether the...
* `run`: Run every source of the suite on its...

### `compose-api suites list`

The suites: their sources, solvers and accepted baseline run.

**Usage**:

```console
$ compose-api suites list [OPTIONS]
```

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api suites runs`

A suite's runs, newest first.

**Usage**:

```console
$ compose-api suites runs [OPTIONS] NAME
```

**Arguments**:

* `NAME`: The suite, e.g. biomodels-ode-sample.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api suites show`

One suite run: per source, whether the solvers agree, match references, and drifted from the baseline.

**Usage**:

```console
$ compose-api suites show [OPTIONS] NAME NUMBER
```

**Arguments**:

* `NAME`: The suite, e.g. biomodels-ode-sample.  [required]
* `NUMBER`: The run's number.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.

### `compose-api suites run`

Run every source of the suite on its solvers; prints the new run's number.

**Usage**:

```console
$ compose-api suites run [OPTIONS] NAME
```

**Arguments**:

* `NAME`: The suite, e.g. biomodels-ode-sample.  [required]

**Options**:

* `--json`: Print JSON (the same as --output json).
* `--help`: Show this message and exit.
