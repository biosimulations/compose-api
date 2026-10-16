# Running items in separate processes, containers and machines

**Status (2026-10-13): research, not a plan.** This chapter surveys how a composite whose items live in different
environments ("islands") could run as one simulation. It covers what process-bigraph already has, the
co-simulation and multiscale-coupling prior art, IPC and parallelism mechanisms, placement and wire compatibility.
It ends with four candidate architectures. They are sketches, not decisions.

Most of it comes from web research done on 2026-10-13, plus a read of process-bigraph's remote `main` on the same day.
Claims that come from memory or general knowledge, not from a fetched source, are marked *(unverified)*. Five
load-bearing claims were re-checked against primary documentation while this chapter was written. They are marked
**(verified 2026-10-13)**, and the results are listed at the end under "Spot-checks".

## 1. Where process-bigraph stands

As of 2026-10-13, process-bigraph's `main` ships transport protocols in
[`process_bigraph/protocols/`](https://github.com/vivarium-collective/process-bigraph/tree/main/process_bigraph/protocols):
`parallel.py`, `ray.py`, `rest.py`, `pool.py`, `session.py`, `git.py` and `clusters/ec2_ssm.py`. Addresses are
resolved by bigraph-schema:
- `normalize_address` splits on the first `:`, and a bare string means `local`.
- `local:a.b.C` is looked up in `core.link_registry`, and `local:!` imports the module directly.
- Protocols are pluggable: register a type plus a `load_protocol` multi-dispatch.

| Protocol | Mechanism | Environment | Notes |
|---|---|---|---|
| `parallel:` ([source](https://raw.githubusercontent.com/vivarium-collective/process-bigraph/main/process_bigraph/protocols/parallel.py)) | `ParallelProcess`: one child per process over a `multiprocessing` Pipe, pickled `(command, args, kwargs)` tuples sent to `run_command`; `forkserver` on Linux, `spawn` on macOS and Windows | same interpreter, same environment | a port of vivarium-core's [`ParallelProcess`](https://vivarium-core.readthedocs.io/en/latest/reference/api/vivarium.core.process.html); `invoke()` sends without waiting |
| `ray:` ([source](https://raw.githubusercontent.com/vivarium-collective/process-bigraph/main/process_bigraph/protocols/ray.py)) | `local:RayProcess` uses round-robin actor pools; a `ray:Foo` address uses sharded batch actors (`RayShadowProcess` → `flush_pending` → one `batch_update` RPC per shard), hooked into Composite | the driver's: **no `runtime_env`** | workers need the same Python stack |
| `rest:` ([source](https://raw.githubusercontent.com/vivarium-collective/process-bigraph/main/process_bigraph/protocols/rest.py)) | JSON over plain HTTP; dict address `{process, host, port}`; endpoints `/process/<name>/{config-schema,initialize,inputs,outputs,update,end}`; a FastAPI server side | whatever the server runs | no error checking, no auth |
| `git:owner/repo@ref#module:callable` | pins to a SHA, builds one `uv` venv per SHA, talks NDJSON over stdio to a worker that uses only the standard library | **a separate venv**: the one cross-environment protocol | allow-list (default `CovertLab/vEcoli`) and a conformance check; its design spec deferred container isolation (choice D1(b)) |

Open points from the fetches, not run:
- **A possible bug in `parallel.py` *(unverified)*.** `get_command_result()` calls `recv()` only when
  `_pending_command` is set, and `send_command` never sets it. So `get()` may return a stale result. Worth checking
  before relying on it.
- **Events stop at the `git:` boundary.** `PBG_*` trace variables reach a `git:` child, but the worker emits no events.

**Nesting and bridge.** A Composite is a Process. Its `bridge` maps the outer ports to inner wires, so a whole
sub-composite can stand anywhere a process can. That is the hook for running a partition of a composite in one
worker (architecture D below).

**Serialization.** bigraph-schema has schema-aware `serialize`, `realize` and `bundle`, but no transport uses them. Every
transport sends raw JSON (`rest:`, `git:`) or pickle (`parallel:`, `ray:`). Numpy arrays and units do not survive a
JSON boundary, and pickle is not safe between environments (section 4.2).

**Outside core.** These exist, but nothing standardises them:
- `vivarium-collective/docker-process`: JSON over TCP to a container. It was last pushed 2025-12.
- `rest-process` and `julia-process`.
- Per-wrapper Docker or subprocess bridges: chaste, tstmd, medyan and artistoo.

The [Process Bigraphs paper](https://arxiv.org/pdf/2512.23754) frames local, parallel, container and REST execution as
interchangeable protocols.

**The gap is isolation, not transport.** Every protocol except `git:` assumes one Python environment. `git:` gives a
venv per SHA but no container, no conda, and no typed serialization. compose-api's validator accepts only `local:`
today (`registry/validation.py`), so a composite using any of these protocols is refused at submission.

## 2. Topologies

Coupled simulations use one of two shapes.

| Topology | Control | Data | Examples | Cost |
|---|---|---|---|---|
| **Hub-and-spoke** (master/worker) | the coordinator owns time and the state tree | every exchange passes through the hub | FMI co-simulation masters; process-bigraph today (`parallel:`, `ray:`, `rest:`, `git:`) | simple; the hub carries all the bytes |
| **Peer-to-peer data, central control plane** | a manager handles discovery, settings and logs | bulk data flows directly between instances | MUSCLE3, preCICE, DACCOSIM's FMU wrappers | scales better; needs instances to reach each other |

### 2.1 FMI 3.0 co-simulation

FMI co-simulation is the hub-and-spoke reference. FMI 3.0 adds three things to co-simulation
([FAQ](https://fmi-standard.org/faq/), [Modelica 2021 slides](https://fmi-standard.org/assets/literature/Modelica_Conference_2021/FMI3Paper_Slides.pdf)):
- early return from `fmi3DoStep`, plus Event Mode;
- Intermediate Update Mode, which allows interpolating and extrapolating masters;
- clocks, for synchronous clocked partitions and scheduled execution
  ([paper](https://ecp.ep.liu.se/index.php/modelica/article/view/179)).

[FMI-LS-BUS](https://ecp.ep.liu.se/index.php/modelica/article/view/1356) is a layered standard that emulates network
buses with clocked binary variables. It is aimed at automotive buses, not at distributing FMUs.

### 2.2 Jacobi and Gauss–Seidel masters

([Co-simulation: State of the art](https://arxiv.org/pdf/1702.00686))

| Master | Order | Inputs | Parallelism |
|---|---|---|---|
| **Jacobi** | all units step at once from the last exchanged values | one exchange old | full |
| **Gauss–Seidel** | units step in sequence, each seeing its predecessors' new outputs | fresher | serial along the chain |

process-bigraph's scheduler fires processes at their intervals and applies the updates afterwards. **That is
effectively a Jacobi master with a step size per process.** This matters for distribution: a Jacobi master can step
remote workers concurrently with no change to the semantics.

### 2.3 Distributed FMI

- **[DACCOSIM](https://hal.archives-ouvertes.fr/hal-01371499)** uses a hierarchical local/global master on clusters, and
  its FMU wrappers pass data peer-to-peer. It is AGPL. The latest material found is from 2019
  ([flyer](https://www.edf.fr/sites/groupe/files/contrib/groupe-edf/recherche-developpement/nos-offres/codes-de-calcul/daccosim_2019_flyer_v7.pdf)).
- **[OMSimulator](https://openmodelica.org/doc/OpenModelicaUsersGuide/1.25/omsimulator.html)** adds TLM connectors for
  numerical stability and has a Python API. It is not cluster-oriented.

## 3. Multiscale coupling frameworks

### 3.1 MUSCLE3

MUSCLE3 is the most relevant prior art. Sources: [docs](https://muscle3.readthedocs.io/),
[ICCS 2020 paper](https://www.iccs-meeting.org/archive/iccs2020/papers/121420406.pdf) and
[repo](https://github.com/multiscale/muscle3).

**Parts.**
- `libmuscle`, with Python, C++ and [Fortran](https://muscle3.readthedocs.io/en/latest/fortran.html) bindings.
- `ymmsl-python`, which reads the model description.
- `muscle_manager`, "a central coordination point that the instances use to find each other". It also collects logs
  and profiling data.

In distributed mode, instances "communicate directly with one another". The license is Apache-2.0. NLeSC and UvA maintain
it, and Ignition Computing offers commercial support.

**The model** ([distributed execution guide](https://muscle3.readthedocs.io/en/latest/distributed_execution.html)) is a
yMMSL YAML file. It defines three levels of thing:

| yMMSL level | Meaning | process-bigraph analogue |
|---|---|---|
| **component** | an abstract submodel in the coupling graph | a process or step node |
| **implementation** | a program that can play a component: executable, args, environment | an address plus the island that can load it |
| **instance** | a running process; `multiplicity` sets how many | a realized process (one or many) |

**Ports and the Submodel Execution Loop (SEL).** Each port belongs to one SEL operator:

| Operator | Role | Direction |
|---|---|---|
| `F_INIT` | receive initial state | receive only |
| `O_I` | intermediate observation | send |
| `S` | state update input | receive |
| `O_F` | final observation | send only |

**Conduits** connect an output port to an input port, for example `macro.state_out: micro.initial_state`. They play
the role of process-bigraph's wires.

**Vector ports** connect one macro instance to N micro instances, and can be resizable
([port API](https://muscle3.readthedocs.io/en/latest/apidocs/libmuscle.port.html)). That is the shape of a variable
population of agents behind one coordinator.

**The reuse loop.** `while instance.reuse_instance():` re-runs a micro model once per macro step, without restarting
the process. This is how a long-lived worker serves many short sub-runs.

**Settings** are either global or prefixed with a component name, and the prefixed value wins.

**Messages** ([tutorial](https://muscle3.readthedocs.io/en/latest/tutorial.html)):
- A message is `Message(timestamp, next_timestamp, data)`. The pair of timestamps is what bridges time scales between
  components with different step sizes. It is the analogue of a process-bigraph interval.
- `Grid` wraps a read-only numpy array with optional index names.
- The wire format is MessagePack. Extension types cover grids of int32, int64, float32, float64 and bool, each carrying
  its shape, memory order and the raw buffer
  ([`mpp_message`](https://muscle3.readthedocs.io/en/master/_modules/libmuscle/mpp_message.html)).

**Per-component environments.** Each program entry has `executable`/`args`, a virtualenv, environment modules and
environment variables. **A different Python environment per component is a first-class feature**, which is exactly
what process-bigraph lacks.

**Containers** ([guide](https://muscle3.readthedocs.io/en/latest/containers.html)):
- A program entry can be `singularity exec …` or `docker run …`.
- `MUSCLE_MANAGER` and `MUSCLE_INSTANCE` must reach the program inside the container. Singularity passes them by
  default, and Docker needs `-e`.
- Docker needs `--network=host` so that components on other machines can connect.
- **The libmuscle version must be identical in every container and in the host's `muscle_manager`; otherwise an
  error is generated when the simulation starts. (verified 2026-10-13)** The page says "the MUSCLE3 library version
  must be identical for all containers". This is a version-locked runtime (section 7).

**MPI.** `execution_model: openmpi` runs MPI components. In C++ an instance receives a communicator and a root rank
([MPI](https://muscle3.readthedocs.io/en/latest/mpi.html)).

**Planning is SLURM-only.** MUSCLE3 detects the SLURM allocation itself, and `muscle3 resources` estimates how many
nodes a model needs. The planner assigns hardware threads per instance, in fixed or virtual allocation mode
([planner](https://muscle3.readthedocs.io/en/latest/apidocs/libmuscle.planner.planner.html)).

**Checkpointing.** A component declares `USES_CHECKPOINT_API` to take part
([deep dive](https://muscle3.readthedocs.io/en/latest/checkpointing_deep_dive.html)).

**Laptops and Windows.** As of 2026-10-13, no statement on macOS or Windows support was found. Outside SLURM the
launcher runs locally. macOS is likely to work, and Windows is unconfirmed *(unverified)*.

**Fit with process-bigraph.**
- Conceptually the fit is very high: ports map to ports, conduits to wires, and the timestamp pair to intervals.
- The mismatch is in the state model. MUSCLE3 passes messages between components. process-bigraph shares one state
  tree and merges updates into it.
- So a process-bigraph coordinator would itself be one MUSCLE3 component, connected to each isolated process by a
  scalar or vector conduit.

### 3.2 preCICE

([terminology](https://precice.org/fundamentals-terminology), [Python bindings](https://api.precice.org/python/latest))
- Partitioned, peer-to-peer coupling through adapters. Coupling is explicit or implicit per time window, with Aitken or
  IQN-ILS quasi-Newton acceleration.
- Mesh mapping (radial basis functions and others). [Waveform iteration](https://arxiv.org/pdf/2001.02654) adds
  interpolation in time within a window.
- It suits PDE solvers coupled across a mesh surface. It is a poor fit for agent populations or ODE networks.

### 3.3 AMUSE

([paper](https://arxiv.org/pdf/1307.3016))
- Each community code runs in its own process behind a Python proxy, called by remote function call.
- The default channel is MPI, with a separate world communicator from the code's own MPI. The alternatives are sockets
  (one machine) and eSTeP (distributed).
- **Separate processes were chosen partly for memory isolation**, because legacy codes rely on global state. That is the
  same motivation as ours, and the proxy model fits process-bigraph's process interface.

### 3.4 Others

| Framework | What | Fit for us |
|---|---|---|
| [MaMiCo](https://github.com/HSU-HPC/MaMiCo) | C++ molecular-continuum coupling; a dynamic number of MD instances; v2.0 adds a Python interface ([2.0](https://openhsu.ub.hsu-hh.de/handle/10.24405/14815)) | domain-specific |
| [libyt](https://arxiv.org/html/2512.11142v1) | embeds Python in every MPI rank for in-situ analysis with mpi4py | in-process, so no isolation |
| ADIOS2 SST ([docs](https://adios2.readthedocs.io/en/master/), [ALCF example](https://docs.alcf.anl.gov/aurora/workflows/adios/)) | publish/subscribe step stream with a pluggable data plane (TCP via EVPath, libfabric RDMA, UCX); readers attach and detach; Python API | streaming large fields to analysis or visualisation; no co-simulation semantics. JAXA measured under 10% of interconnect bandwidth over TCP ([report](https://www.jss.jaxa.jp/en/ar/e2019/11556/)) |

### 3.5 Prior isolation in simulation composition

- **vivarium-core and `parallel:`** use one process per Process, all in the same environment.
- **[BioSimulators](https://docs.biosimulations.org/concepts/conventions/simulator-images/)** uses one Docker image per
  simulator with a fixed CLI (`-i archive.omex -o outdir`). It is batch-only, with no stepping.
- **Tellurium and libRoadRunner** run in-process: C++ with an LLVM JIT.
- **SED-ML/COMBINE** couples tools through files between whole runs.

All of these isolate only at **run granularity**. As of 2026-10-13, nothing in this ecosystem couples across
environments step by step, except through MUSCLE3-like frameworks.

## 4. IPC mechanisms

### 4.1 multiprocessing

- **Start methods.** Python 3.14 changed the POSIX default from `fork` to `forkserver` (gh-84559). `spawn` stays the
  default on macOS (since 3.8) and Windows. `fork` is no longer the default on any platform.
  **(verified 2026-10-13, [docs](https://docs.python.org/3.14/library/multiprocessing.html))**. The docs add one
  exception: `spawn` is used when there is no writable temporary directory. They note that 3.14.8 (unreleased) moves
  that decision to first use.
- **The isolation limit.** With `spawn` or `forkserver`, the child re-imports `__main__` and everything is pickled. The
  child is still the **same interpreter and environment**, so multiprocessing gives process isolation (memory,
  crashes, the GIL) but no dependency isolation.
- **`shared_memory`** ([docs](https://docs.python.org/3/_sources/library/multiprocessing.shared_memory.rst.txt)):
  - It gives zero-copy numpy arrays within one host.
  - A process not started by multiprocessing gets its own resource tracker, which can unlink a segment early. Use
    `track=False`, available from 3.13.
  - Windows ignores `track` and frees a segment when its last handle closes.
  - Crossing a container boundary needs a shared `/dev/shm`.

### 4.2 Serialization

| Format | Properties | Across environments? |
|---|---|---|
| **pickle 5** ([PEP 574](https://peps.python.org/pep-0574/)) | out-of-band `PickleBuffer`s through `buffer_callback`, separating metadata from zero-copy buffers; Ray uses it ([discussion](https://discuss.ray.io/t/arrow-version-compatibility/2444)) | **no** (see below) |
| **msgpack** ([msgpack.org](https://msgpack.org/)) | compact, language-neutral, extension types; MUSCLE3's wire format | yes, given a schema for the extension types |
| **Arrow IPC** | stable columnar wire format; format V5 is backward compatible, and old readers must detect features they cannot read ([Versioning](https://arrow.apache.org/docs/format/Versioning.html)); extension types carry `ARROW:extension:name`; canonical types include `FixedShapeTensor` ([extending pyarrow](https://arrow.apache.org/docs/python/extending_types.html)) | yes, and suits ragged tables |
| **Arrow Flight** | gRPC carrying Arrow record batches | yes |
| **Arrow Plasma** | shared-memory object store; deprecated in 10.0, **removed in 12.0** ([12.0 release](https://arrow.apache.org/blog/2023/05/02/12.0.0-release)) | gone |
| **[Cap'n Proto](https://capnproto.org/)** | zero-copy reads, capability-based RPC; Python support is thinner *(unverified)* | yes |

**Why pickle is not environment-neutral.**
- A pickle names classes by module path, so both sides need the same classes at compatible versions.
- The sharp case: NumPy 2 pickles reference `numpy._core`, which NumPy before 1.26 cannot load
  ([NumPy commit](https://redirect.github.com/numpy/numpy/commit/bdb190d8cf3ad2d8d6fd9264852ba35d71cf7417)). Two islands,
  one on NumPy 1 and one on NumPy 2, cannot exchange pickled arrays in both directions.
- Unpickling also executes code, which is a security risk on any boundary that is not fully trusted.

### 4.3 Transports

| Transport | Notes |
|---|---|
| **ZeroMQ** ([zmq_ipc](https://libzmq.readthedocs.io/en/zeromq4-1/zmq_ipc.html)) | `ipc://` on Windows needs libzmq ≥ 4.3.3 with AF_UNIX, and fails in some service contexts ([thread](https://lists.zeromq.org/pipermail/zeromq-dev/2022-March/033700.html)); `tcp://127.0.0.1` works everywhere |
| **[gRPC](https://grpc.io/)** | schema'd, multi-language RPC with streaming |
| **Unix domain sockets** | Windows 10 1803+ has AF_UNIX in Winsock *(unverified)*. But **asyncio on Windows does not support `loop.create_unix_connection()` or `loop.create_unix_server()`** ("The `socket.AF_UNIX` socket family is specific to Unix") **(verified 2026-10-13, [asyncio platforms](https://docs.python.org/3/library/asyncio-platforms.html))**; the bpo-33408 PR was closed ([PR](https://github.com/python/cpython/pull/14823)) |
| **Loopback TCP** | the portable choice for sockets, on every OS |

### 4.4 Worker protocols worth copying

**The Jupyter kernel protocol** ([docs](https://jupyter-protocol.readthedocs.io/en/latest/kernels.html)) is the best
existing model of a separately installed, language-agnostic worker with liveness checks and interrupts.
- It uses five ZeroMQ sockets:
  - shell, for requests and replies;
  - control, for priority messages such as shutdown;
  - iopub, for broadcasts;
  - stdin;
  - heartbeat.
- A JSON connection file carries the ports and an HMAC key.
- `kernel_info_reply.protocol_version` negotiates the protocol version.

**MCP over stdio** ([spec](https://modelcontextprotocol.io/specification/latest/basic/transports/stdio)) is
newline-delimited JSON-RPC over a child's stdin and stdout, with stderr for logs. process-bigraph's `git:` worker uses
the same shape (NDJSON over stdio).

**LSP** ([spec](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.18/specification)) is
JSON-RPC framed with a `Content-Length` header.

**Docker Engine API `attach`**
([reference](https://bump.sh/christophedujarric/hub/docker/doc/docker-engine-api/operation/operation-containerattach))
turns the HTTP connection into a raw socket. Without a TTY, stdout and stderr are multiplexed with an 8-byte header:
the stream type, then a big-endian length. `docker run -i --rm` without `-t` avoids that framing.

**Why stdio is the most portable.** stdio framing passes unchanged through `docker run -i`, `apptainer exec`, `ssh` and
`srun`. It needs no ports, no network set-up and no shared filesystem for sockets, and it behaves the same on Windows.
No other option has that property.

## 5. Parallelism

### 5.1 Threads, OpenMP and free-threaded Python

- Free-threaded CPython is officially supported but optional in 3.14 ([PEP 779](https://peps.python.org/pep-779/)). It
  costs roughly 5–10% single-threaded.
- It does not help with isolation: one interpreter still means one dependency set.
- C++ codes that use OpenMP, PhysiCell among them, already parallelise internally. Such a worker should be given cores
  through `OMP_NUM_THREADS`, not multiplied into more workers.

### 5.2 MPI

- **mpi4py `MPIPoolExecutor`** uses MPI-2 dynamic process management
  ([docs](https://mpi4py.readthedocs.io/en/4.1.2/mpi4py.futures.html)).
- **`MPI_Comm_spawn` under SLURM is fragile.** The Slurm PMIx plugin returns "not supported"
  ([SchedMD #9979](https://support.schedmd.com/show_bug.cgi?id=9979)). Some users report it working under `salloc` but
  not under `sbatch` ([slurm-users](https://lists.schedmd.com/pipermail/slurm-users/2021-June/007494.html)). Launch all
  ranks up front instead.
- **Apptainer and MPI** ([docs](https://apptainer.org/docs/user/1.5/mpi.html)):
  - The **hybrid** model is preferred. The host's `mpirun` launches `apptainer exec`, with an ABI-compatible MPI inside
    the image.
  - The **bind** model mounts the host's MPI into the image, and is less portable.
- **Fit:** good for one tightly coupled code, poor as a general coupling bus. In practice it is not on Windows laptops.

### 5.3 Ray

([RuntimeEnv](https://docs.ray.io/en/latest/ray-core/api/doc/ray.runtime_env.RuntimeEnv.html))
- `runtime_env` can be set per actor or per task. It takes `pip` or `conda` (not both at the top level), or a
  container (`image_uri` / `container`).
- **Container environments run through Podman. (verified 2026-10-13, with a nuance)**
  - The [Serve multi-app container guide](https://docs.ray.io/en/latest/serve/advanced-guides/multi-app-container.html)
    says the feature "uses Podman to start and run containers" and is "experimental and the API is subject to change".
  - "The Ray version and Python version in the container *must* match those of the host environment exactly."
  - When the raylet itself runs in a container, that container must be `--privileged`.
  - The `RuntimeEnv` API page describes the field as "a given Docker container image" and names no runtime.
- SLURM support is community-maintained ([guide](https://gitea.com/qu-bit/ray/src/branch/master/doc/source/cluster/slurm.rst)).
- **Conclusion.** pip or conda environments per actor are attractive on laptops and in the cloud. Container environments
  on Apptainer-only HPC are effectively unsupported. The `ray:` protocol (section 1) does not use `runtime_env` at all
  today.

### 5.4 Dask, Parsl, Globus Compute and remote objects

| Framework | Heterogeneous environments | Fit |
|---|---|---|
| **Dask** ([resources](https://distributed.dask.org/en/stable/resources.html)) | abstract worker resources plus `workers=` / `allow_other_workers`; different environments mean launching different worker pools by hand; all workers need compatible `distributed`, cloudpickle and numpy *(unverified)* | weak for stateful stepping |
| **Parsl** ([HTEx](https://parsl.readthedocs.io/en/latest/stubs/parsl.executors.HighThroughputExecutor.html)) | a `worker_init` per executor and executors on several sites, so one environment per executor works well | coarse steps |
| **Globus Compute** ([dynamic containers](https://globus-compute.readthedocs.io/en/stable/tutorials/dynamic_containers.html)) | the user endpoint config is a Jinja template, so the container type (docker, apptainer, singularity) and URI can be chosen per submission; warm containers are reused | function-as-a-service: stateless steps, not stateful stepping |
| **[Pyro5](https://pypi.org/project/Pyro5/)** / RPyC | remote objects; Pyro5 allows only safe serializers (serpent, json, msgpack), supports UDS and TLS, and is in "super low maintenance mode" | proxy model fits; maintenance risk |
| **Celery** | queue-based | latency too high for lockstep |

### 5.5 Pilot systems inside one SLURM allocation

| System | Notes |
|---|---|
| [QCG-PilotJob](https://qcg-pilotjob.readthedocs.io/en/latest/overview.html) | submission by file or API; used with EasyVVUQ and MUSCLE3 tooling |
| [HyperQueue](https://it4innovations.github.io/hyperqueue/) | resources per task; needs no privileges |
| [RADICAL-Pilot](https://radicalpilot.readthedocs.io/) with [Flux](https://flux-framework.org/) | up to about 930 tasks/s, against srun's 152 tasks/s on Frontier ([study](https://arxiv.org/html/2509.20819v1), [ExaWorks SDK](https://arxiv.org/pdf/2407.16646)) |

These launch long-lived workers efficiently inside an allocation, but none is a coupling bus. They are a launcher
layer under one of the architectures in section 9.

## 6. Data exchange cost

### 6.1 Cost classes

The orders of magnitude below are general knowledge *(unverified)*, not measurements of our hardware.

| Class | Cost per exchange |
|---|---|
| same-process reference | about 0 |
| shared memory or memory-map | µs, then memory bandwidth |
| pickle 5 or Arrow over a loopback socket | tens of µs, then about 1–5 GB/s |
| TCP between nodes | about 10–100 µs, then link bandwidth |
| Docker Desktop on macOS or Windows | an extra VM network hop on top |

Two regimes follow:
- **Small ODE states** (kB) are dominated by latency. Batch per tick, as the `ray:` protocol's `batch_update` already
  does.
- **Meshes and fields** (MB to GB) are dominated by bandwidth. Use zero-copy (shared memory, Arrow), or keep the field
  where it is produced and send only what consumers need.

Zarr suits exchange at checkpoint or analysis rate, not per tick.

### 6.2 Lockstep vs time-window exchange

- **Lockstep.** Each tick, every worker waits for every input it needs. With a Gauss–Seidel order this serialises the
  chain.
- **Time windows (Jacobi).** Each worker steps a whole window from the values exchanged at the window's start, and all
  workers step concurrently, at the cost of one window of lag. MUSCLE3's `next_timestamp` and preCICE's coupling
  windows formalise this.
- process-bigraph's scheduler is already Jacobi-like (section 2.2). So distributing it with per-interval windows
  changes timing, not semantics.

## 7. Placement of items that exist on several islands

An item (an adapter, an IO step, a plotting step) can be installed on several islands. Something has to decide which
island runs each instance of it.

### 7.1 Prior art

**Ray.**
- Locality-aware scheduling prefers the node holding the most argument bytes. It applies to tasks only, not actors
  ([scheduling](https://docs.ray.io/en/latest/ray-core/scheduling/index.html)).
- Placement groups use `PACK`, `STRICT_PACK`, `SPREAD` and `STRICT_SPREAD` bundle strategies
  ([API](https://docs.ray.io/en/latest/ray-core/api/doc/ray.util.placement_group.html)).
- `NodeAffinitySchedulingStrategy(soft=…)` pins work to a node
  ([API](https://docs.ray.io/en/latest/ray-core/api/doc/ray.util.scheduling_strategies.NodeAffinitySchedulingStrategy.html)).
- Serve can prefer replicas on the same node through `_prefer_local_routing`, which is private
  ([routing](https://docs.ray.io/en/latest/serve/api/doc/ray.serve.request_router.LocalityMixin.html)).
- Ray Data fuses map operators specifically "to reduce serialization overhead"
  ([internals](https://ray.readthedocs.io/en/latest/data/data-internals.html)).

**Dask.** It schedules toward workers that hold the inputs. `workers=` with `allow_other_workers` gives soft or hard
pinning, and resources act as capability tags
([resources](https://distributed.dask.org/en/stable/resources.html),
[work stealing](https://dask.discourse.group/t/understanding-work-stealing/335)).

**MUSCLE3.**
- The planner assigns hardware threads per instance, and reasons over macro/micro relations in the model graph.
- Per the distributed-execution guide, instances that are idle at different times (a macro model waiting on its micro
  models) may share cores.
- Placement is per **component**. MUSCLE3 has no notion of one component replicated across environments.

### 7.2 Heuristics suggested by the prior art

This is a sketch, not a decision.

| # | Rule | Reason |
|---|---|---|
| 1 | **Version pins first.** Each island is a capability set: the items it can load, at given versions. An item may run only on islands whose version satisfies the composite's pin | restricts the candidates before any cost is weighed |
| 2 | **Producer fusion.** Adapters, IO and data-processing steps default to the **producer's** island | they usually shrink or reshape large state, so fusing them cuts the bytes that cross (Ray Data's operator fusion) |
| 3 | **Viz at the consumer.** Plotting runs on the consumer's or coordinator's island when it reads emitted history, not live state | history is already at the coordinator |
| 4 | **Solvers next to the large field** | the field is the most expensive thing to move |
| 5 | **Min-cut on cut-wire bytes.** Cost a placement as bytes on cut wires × crossing cost (section 6.1), plus load | this is graph partitioning on the wiring graph; the bytes-local rule of Ray and Dask is its cheap greedy form |
| 6 | **Pin override.** A composite can pin an item to an island, softly or hard | as Ray's `NodeAffinity(soft=True)` or Dask's `allow_other_workers=True` |

## 8. Wire compatibility across islands

State that crosses an island boundary must mean the same thing on both sides. The two deployed environments already
disagree on the core: as of 2026-10-13, `registry_env` runs process-bigraph 1.0.5 with bigraph-schema 1.0.14, and
`viva-pde-particle` runs 1.8.5 with 1.7.0 (`compose_api/registry/manifests/*.json`).

### 8.1 Three approaches in the prior art

| Approach | Examples | Behaviour |
|---|---|---|
| **Version-locked runtime** | MUSCLE3: an error at start-up on a libmuscle mismatch ([containers](https://muscle3.readthedocs.io/en/latest/containers.html), verified 2026-10-13); Ray containers: identical Ray and Python versions (verified 2026-10-13) | simple, and the strictest: every island carries the same runtime |
| **Negotiation** | FMI 3.0 checks `fmiVersion` and an instantiation token linking the model description to the binary *(unverified detail, [spec](https://fmi-standard.org/docs/3.0))*; Jupyter reports `protocol_version` in `kernel_info` | sides agree a version at handshake |
| **Schema evolution** | Avro resolves a writer schema against a reader schema ([Resolver](https://avro.apache.org/docs/1.12.0/api/java/org/apache/avro/Resolver.html)); Confluent registry modes BACKWARD, FORWARD, FULL and their `_TRANSITIVE` variants ([docs](https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.md)); protobuf field-number rules and `reserved`; Arrow format-version rules and extension-type names | sides may differ, within declared compatibility rules |

**A cautionary case.** Pickled numpy across NumPy 1 and 2 breaks (section 4.2). The wire format should be
**schema-described data**: bigraph-schema `serialize`/`deserialize` into msgpack or Arrow, never pickle across islands.

### 8.2 Per-port schema hashes checked at handshake

The following is inference from the prior art.
- Give each port type a canonical serialized schema and a hash of it. compose-api already treats a hash of the
  definition text as an environment's identity.
- At handshake, each island reports, per item, `(item@version, port schemas and hashes, bigraph-schema version)`.
- The coordinator checks every cut wire against a rule: the hashes are identical, or the schemas are compatible in the
  BACKWARD or FULL sense.
- Two versions of one item on two islands are acceptable if their **port schemas** agree. Any behavioural difference
  then becomes a provenance and registry question (record the version per placement), not a transport question.
- That is why placement must also be version-pinned (rule 1 in 7.2).

## 9. Comparison

| Option | Mechanism | Latency / throughput | HPC | Linux | macOS | Win | Containers | Maturity | Fit to the port/state model |
|---|---|---|---|---|---|---|---|---|---|
| mp Pipe (`parallel:`) | pickled tuples | µs / pickle-bound | yes | yes | yes (spawn) | yes (spawn) | no (same env) | stdlib | good, but no isolation |
| `shared_memory` + Pipe | zero-copy buffers | memory bandwidth | node-local | yes | yes | yes (quirks) | needs shared `/dev/shm` | stdlib | good for arrays |
| stdio JSON-RPC / msgpack (MCP/LSP style; `git:`) | child stdin/stdout | ~10–100 µs | yes (srun, apptainer) | yes | yes | yes | best (any `exec -i`) | pattern | very good |
| ZeroMQ | sockets, patterns | ~10–50 µs | yes | yes | yes | tcp yes, ipc partial | yes | high | good (Jupyter precedent) |
| gRPC / Arrow Flight | HTTP/2 + protobuf or Arrow | ~100 µs, GB/s columnar | yes | yes | yes | yes | yes | high | good with a schema |
| REST (`rest:`) | JSON over HTTP | ms | yes | yes | yes | yes | yes | trivial | OK for coarse steps |
| MUSCLE3 | manager + P2P TCP, msgpack Grid | µs–ms, P2P | **SLURM native** | yes | likely | unconfirmed | Apptainer, Docker; version-locked | mature research | **very high** (ports, conduits, timestamps) |
| preCICE | P2P, mesh mapping | high bandwidth | yes | yes | partial | no | yes | mature | PDE interfaces only |
| AMUSE | MPI or sockets, remote calls | µs (MPI) | yes | yes | yes | no | limited | mature (astro) | proxy model fits |
| ADIOS2 SST | step streams, RDMA or TCP | high bandwidth | yes | yes | partial | partial | yes | mature | viz and analysis fan-out |
| Ray (+ `runtime_env`) | actors, object store | ~100 µs–ms | community SLURM | yes | yes | beta | Podman only, experimental | high | good; pip/conda isolation |
| Dask | tasks, actors | ms | dask-jobqueue | yes | yes | yes | separate pools | high | weaker for stateful stepping |
| Parsl / Globus Compute | executors / FaaS | ms–s | **strong** | yes | yes | client | Apptainer per endpoint | high | coarse steps only |
| MPI / mpi4py | ranks | µs | **strong** | yes | yes | rare | hybrid Apptainer | very high | single codes |
| Pilots (QCG, HQ, RP, Flux) | launchers | task-launch rate | **strong** | yes | no | no | yes | high | launcher only |

The latency figures are classes from section 6.1, not measurements. The platform cells for preCICE, AMUSE, ADIOS2 and
the pilots were not checked one by one *(unverified)*.

## 10. Candidate architectures (sketches, not decisions)

### A. A stdio worker protocol (the "kernel" model)

- A small process-bigraph worker runtime, `pbg-worker`, speaks length-framed msgpack JSON-RPC over stdio. It generalises
  the `git:` worker's NDJSON protocol.
- Its verbs are `describe` (ports, schemas, versions), `initialize`, `update(state, interval)` and `end`.
- The coordinator starts it with whatever command fits the island: `python -m`, `conda run`, `pixi run`,
  `docker run -i`, `apptainer exec`, or `srun … apptainer exec`.
- Large arrays go out of band: through shared memory on the same host, or a side socket otherwise.
- **One code path on Windows, macOS, Linux and HPC.**
- Downside: the hub carries all the data.

### B. MUSCLE3 as the HPC backend

- Compile a process-bigraph composite to yMMSL. Each isolated process becomes a MUSCLE3 component whose program is
  `apptainer exec <image> pbg-muscle-worker`, and the coordinator becomes a central component.
- It brings SLURM placement, MPI, peer-to-peer data and checkpointing.
- Costs:
  - every image must carry the identical libmuscle version;
  - the laptop and Windows story is still unconfirmed;
  - the state tree and its update-merge have to be expressed over message passing.
- It could sit behind the same worker verbs as A, so that A runs locally and B on clusters.

### C. Ray with a `runtime_env` per actor

- Extend the existing `ray:` protocol so each actor gets a pip or conda environment. Islands become named `runtime_env`s,
  placed through `NodeAffinity` or placement groups.
- The best developer experience on laptops and in the cloud.
- Weak on Apptainer HPC: container environments are Podman-only and experimental, and SLURM support is
  community-maintained.

### D. An island-aware partitioned composite (combines with A or B)

- Partition the wiring graph by island capability, version pins and cut-wire bytes (section 7.2).
- Run each partition as a sub-composite (Composite nesting and `bridge`, section 1) in one long-lived worker. A
  replicated item is fused with its producer.
- Only cut-wire state crosses islands, as schema-hashed msgpack or Arrow, checked at handshake (section 8.2).
- Each worker uses its own internal parallelism (OpenMP, GPU, free-threading).

| | A | B | C | D |
|---|---|---|---|---|
| Laptop (macOS, Windows) | yes | unconfirmed | yes | via A |
| SLURM + Apptainer | yes (`srun … apptainer exec`) | native | weak | via A or B |
| Data path | through the hub | P2P | object store | only cut wires cross |
| New code | worker runtime, framing | yMMSL compiler, worker | `runtime_env` plumbing | partitioner, handshake |
| Version lock | none beyond the wire schema | libmuscle identical everywhere | Ray and Python identical in containers | inherits from A or B |

## Constraints

1. Every process-bigraph protocol except `git:` runs in one Python environment. `git:` gives a uv venv per SHA but no
   conda, no container and no typed serialization (2026-10-13).
2. No transport serializes through bigraph-schema. Raw JSON loses numpy arrays and units, and pickle is not
   environment-neutral (NumPy 1 vs 2).
3. The deployed islands already run different cores (process-bigraph 1.0.5 vs 1.8.5). The wire format has to be stable
   across bigraph-schema 1.0.14 and 1.7.0, or the cores have to converge first.
4. compose-api's validator accepts only `local:` addresses against `registry_env`. Any cross-island composite is refused
   at submission today.
5. Production is SLURM with Apptainer, and images cannot be built on the nodes (fakeroot fails;
   `docs/plan-environment-builds.md`). Podman on the nodes is not established, so Ray's container environments cannot
   be assumed there.
6. The scheduler is Jacobi-like, so windowed, concurrent stepping of remote workers preserves its semantics.
7. `MPI_Comm_spawn` is unreliable under SLURM, so workers must be launched up front, not spawned on demand.
8. On Windows, asyncio cannot serve or connect Unix sockets: use stdio or loopback TCP.
9. Version-locked coupling runtimes (MUSCLE3, Ray containers) put the same runtime version into every island image.

## Unknowns

- Whether Apptainer instances in one SLURM job, or across jobs, can reach each other over TCP on our cluster. This is
  untested. stdio over `srun` avoids the question.
- Whether MUSCLE3 runs on macOS and Windows, and outside SLURM beyond a single machine.
- The real exchange costs on our nodes and storage. The figures in section 6.1 are classes, not measurements.
- Whether the `parallel.py` `get_command_result` stale-result issue is real.
- Which side owns serialization of typed state at a boundary: the coordinator, the worker, or bigraph-schema in both.
  The answer is coupled to the core version split.
- Whether bigraph-schema's `serialize` output is stable enough between 1.0.x and 1.7+ to hash per port, or whether a
  separate canonical schema form is needed.
- How emitters and `PBG_*` events cross the boundary. The `git:` worker emits none today.
- Whether a per-tick hub (A) is fast enough for the composites people run, or whether P2P (B, D) is needed from the
  start.

## Spot-checks (2026-10-13)

| Claim | Verdict | Source |
|---|---|---|
| MUSCLE3 needs an identical libmuscle version in every container and in the manager | **confirmed**: "must be identical for all containers", otherwise an error at start-up; the host manager too | [containers](https://muscle3.readthedocs.io/en/latest/containers.html) |
| Ray container `runtime_env` is Podman-only | **confirmed, with a nuance**: the Serve guide says Podman, experimental, Ray and Python must match the host exactly, a privileged raylet container; the `RuntimeEnv` API page names a "Docker container image" and no runtime. The report's "image must contain a matching Ray version" is strengthened to "Ray *and Python* versions must match exactly" | [Serve containers](https://docs.ray.io/en/latest/serve/advanced-guides/multi-app-container.html), [RuntimeEnv](https://docs.ray.io/en/latest/ray-core/api/doc/ray.runtime_env.RuntimeEnv.html) |
| asyncio has no `create_unix_server` on Windows | **confirmed**, and also no `create_unix_connection`, on all Windows event loops | [asyncio platforms](https://docs.python.org/3/library/asyncio-platforms.html) |
| Python 3.14's default start method on POSIX is `forkserver` | **confirmed**; `spawn` stays default on macOS and Windows; `spawn` is used when no temporary directory is writable | [multiprocessing](https://docs.python.org/3.14/library/multiprocessing.html) |

## Sources

- process-bigraph protocols: https://github.com/vivarium-collective/process-bigraph/tree/main/process_bigraph/protocols
  (`parallel.py`, `ray.py`, `rest.py`, `git.py`); Process Bigraphs paper https://arxiv.org/pdf/2512.23754;
  vivarium-core `ParallelProcess` https://vivarium-core.readthedocs.io/en/latest/reference/api/vivarium.core.process.html
- FMI: https://fmi-standard.org/faq/, https://fmi-standard.org/docs/3.0,
  https://fmi-standard.org/assets/literature/Modelica_Conference_2021/FMI3Paper_Slides.pdf,
  https://ecp.ep.liu.se/index.php/modelica/article/view/179, https://ecp.ep.liu.se/index.php/modelica/article/view/1356
- Co-simulation survey: https://arxiv.org/pdf/1702.00686
- DACCOSIM: https://hal.archives-ouvertes.fr/hal-01371499; OMSimulator:
  https://openmodelica.org/doc/OpenModelicaUsersGuide/1.25/omsimulator.html
- MUSCLE3: https://muscle3.readthedocs.io/, https://github.com/multiscale/muscle3,
  https://www.iccs-meeting.org/archive/iccs2020/papers/121420406.pdf,
  https://muscle3.readthedocs.io/en/latest/distributed_execution.html,
  https://muscle3.readthedocs.io/en/latest/containers.html, https://muscle3.readthedocs.io/en/latest/mpi.html,
  https://muscle3.readthedocs.io/en/latest/checkpointing_deep_dive.html,
  https://muscle3.readthedocs.io/en/latest/tutorial.html,
  https://muscle3.readthedocs.io/en/latest/apidocs/libmuscle.planner.planner.html
- preCICE: https://precice.org/fundamentals-terminology, https://arxiv.org/pdf/2001.02654; AMUSE:
  https://arxiv.org/pdf/1307.3016; MaMiCo: https://github.com/HSU-HPC/MaMiCo; libyt:
  https://arxiv.org/html/2512.11142v1; ADIOS2: https://adios2.readthedocs.io/en/master/,
  https://www.jss.jaxa.jp/en/ar/e2019/11556/
- BioSimulators simulator images: https://docs.biosimulations.org/concepts/conventions/simulator-images/
- Python: https://docs.python.org/3.14/library/multiprocessing.html,
  https://docs.python.org/3/library/asyncio-platforms.html, https://peps.python.org/pep-0574/,
  https://peps.python.org/pep-0779/, https://github.com/python/cpython/pull/14823
- NumPy 2 pickle path: https://redirect.github.com/numpy/numpy/commit/bdb190d8cf3ad2d8d6fd9264852ba35d71cf7417
- Arrow: https://arrow.apache.org/docs/format/Versioning.html, https://arrow.apache.org/docs/python/extending_types.html,
  https://arrow.apache.org/blog/2023/05/02/12.0.0-release
- ZeroMQ: https://libzmq.readthedocs.io/en/zeromq4-1/zmq_ipc.html; Jupyter:
  https://jupyter-protocol.readthedocs.io/en/latest/kernels.html; MCP:
  https://modelcontextprotocol.io/specification/latest/basic/transports/stdio; LSP:
  https://microsoft.github.io/language-server-protocol/specifications/lsp/3.18/specification
- MPI: https://mpi4py.readthedocs.io/en/4.1.2/mpi4py.futures.html, https://support.schedmd.com/show_bug.cgi?id=9979,
  https://apptainer.org/docs/user/1.5/mpi.html
- Ray: https://docs.ray.io/en/latest/ray-core/api/doc/ray.runtime_env.RuntimeEnv.html,
  https://docs.ray.io/en/latest/serve/advanced-guides/multi-app-container.html,
  https://docs.ray.io/en/latest/ray-core/scheduling/index.html,
  https://docs.ray.io/en/latest/ray-core/api/doc/ray.util.placement_group.html,
  https://ray.readthedocs.io/en/latest/data/data-internals.html
- Dask: https://distributed.dask.org/en/stable/resources.html; Parsl:
  https://parsl.readthedocs.io/en/latest/stubs/parsl.executors.HighThroughputExecutor.html; Globus Compute:
  https://globus-compute.readthedocs.io/en/stable/tutorials/dynamic_containers.html; Pyro5: https://pypi.org/project/Pyro5/
- Pilots: https://qcg-pilotjob.readthedocs.io/en/latest/overview.html, https://it4innovations.github.io/hyperqueue/,
  https://radicalpilot.readthedocs.io/, https://flux-framework.org/, https://arxiv.org/html/2509.20819v1
- Schema evolution: https://avro.apache.org/docs/1.12.0/api/java/org/apache/avro/Resolver.html,
  https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.md
- compose-api: `compose_api/registry/validation.py`, `compose_api/registry/manifests/*.json`,
  `docs/plan-environment-builds.md`
