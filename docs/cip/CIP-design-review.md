# Composition Interface Protocol: design review

**Status:** draft for design review, 2026-09-09. Not normative. Nothing here is a recommendation; each decision in
§4 ends with a blank line for the reviewer's call.

## 0. How to read this

The TR&D3 grant promised, in Year 1, a Composition Interface Protocol (CIP): a process interface, a composite
specification, orchestration methods, and an exchange format. What exists today is an implementation
(`bigraph-schema` 1.6.0 and `process-bigraph` 1.8.4), a paper whose supplement claims to hold the formal
specification, and about ten design documents, but no single versioned specification. This document is the step
before writing one. It does three things and nothing else:

1. **§1 Proposed.** What the grant text actually says, quoted verbatim, so the proposal can be read without the
   filter of what was later built.
2. **§2 Built.** What the two libraries do today, with every claim cited to a file and line at a pinned commit, so
   the description can be checked rather than trusted.
3. **§4 Decide.** Where the two disagree, or where the code never had to settle a question the grant raised, stated
   as a decision with options and their costs. No option is marked preferred.

§3 is a vocabulary map between the grant's words and the code's identifiers. Appendix A lists the tests that pin
each semantic; Appendix B lists sources and the exact commits cited.

**What this document deliberately does not do.** It does not restate material that already exists. Where an
existing document covers a topic, it is cited once and linked: the two-layer split and "the laws" in
`process-bigraph/docs/architecture.md` §7; sites, `fill`, and groundness in
`bigraph-schema/docs/superpowers/specs/2026-07-30-template-slot-primitive-design.md`; the contract model in
`bigraph_schema/contract.py`; address resolution failure modes in `bigraph-schema/doc/address_portability_and_discovery.md`;
update sentinels and batch reconciliation in `bigraph-schema/doc/method_api_spec.md` and `doc/reconcile_audit.md`;
the `git:` transport in `process-bigraph/docs/superpowers/specs/2026-07-31-git-remote-protocol-design.md`; the
document anatomy tutorial in `process-bigraph/docs/concepts/composites-and-templates.md`. The arXiv paper
(Agmon & Spangler, "Process Bigraphs and the Architecture of Compositional Systems Biology", 2512.23754) states that
its Supplementary Materials "provides the formal specification"; that supplement is not in any local checkout and
is not summarized here. Whether this document, the supplement, or a third artifact becomes the specification is
itself a decision (§4, D-N).

**Scope note on examples.** Three wrapped simulators were sampled for ecosystem practice: `pbg-vcell-fvsolver`,
`spatio-flux`, and the whole-cell project `v2ecoli` via its build `sms-ecoli`. The whole-cell project is unusually
large and under active development; it is cited here for three conventions only and was not examined in depth.
Nothing in this review should be read as characterizing that project.

**Grant clock.** Project period 03/01/2024 – 02/28/2029. Y1 = Mar 2024–Feb 2025, Y2 = Mar 2025–Feb 2026,
**Y3 = Mar 2026–Feb 2027 (now)**, Y4 = Mar 2027–Feb 2028, Y5 = Mar 2028–Feb 2029.

---

## 1. What the grant proposed

All quotations are from `TR&D3 - Research Strategy.md`, Aim 2 unless noted. Nothing is paraphrased in this section.

### 1.1 The three parts

> This requires three things – (1) composition interface protocol - a standardized interface for sub-models, (2)
> Composition exchange format - a composite specification "wiring diagram" that declares how the sub-models connect,
> and (3) execution methods for orchestrating the co-simulation.

The framing metaphor, and the ambition:

> This standard protocol will allow different simulators, models, and data to talk with each other; analogous to how
> the internet protocol (TCP/IP) allows servers to communicate with each other and with clients across the internet.

The basic units, from the Figure 1 caption:

> The basic units of composite simulators are processes and states. Processes wrap around simulation tools, and
> expose an interface made of different ports, which is the processes' set of inputs and outputs variables. Shareable
> states are external to the processes for easy linking with other processes

### 1.2 The process interface

> Process interface is the API for individual simulation tools. This includes ports that specify data types, using
> an abstraction of variables developed with TR&D1 and a formal ontology developed with TR&D 2 that will include
> annotations such as units, semantics, and provenance. It will support distributed, network-based communication
> using a remote procedure call. To meet the interface, processes will only be required to send structured messages
> in response to queries about their ports and variable types, parameters, initial state, annotations, and the update
> function that is called iteratively during runtime.

Figure 2 gives the proposed declaration format:

```json
{"process_id": {
    "process_location": "URI 0-000-00000-0",
    "update_method": "KiSAO:CVODE",
    "interface": {
        "port1": "data type",
        "port2": "data type"}}}
```

with the caption:

> It includes a field for the KiSAO id, which is the simulation algorithm the simulator implements. The interface
> declares the process ports, which are formal interfaces for accessing variables. This is also where TR&D2's
> annotations will go, which specify units and other semantic content.

### 1.3 The composite specification

> Composite specification that declares how individual processes are wired together into composite simulators. The
> wires go from the individual process's ports to shared state variables that other processes can connect to. The
> ports for all processes that share a state need to match, with the same data type and annotations. Formalizing this
> specification will allow for more automatic composition, as processes can only be linked through variables that
> have the same type. Adapter processes that can translate between data types will play an important role

Figure 3 gives the proposed exchange format, "a simplistic, but illustrative, prototype":

```json
{"processes": {
    "ODE": {"process_id": ["Tellurium", "v2.2.3"], "config": {"model": "sbmlfile1"}},
    "SSA": {"process_id": ["COPASI", "v4.38"],    "config": {"model": "sbmlfile2"}},
    "concs-to-counts adapter": {"process_id": ["counts_concs", "v0.1"], "config": {}}},
 "wires": {
    "ODE": {"species": "concentrations"},
    "SSA": {"counts": "counts", "volume": "volume"},
    "concs-to-counts adapter": {
        "concentrations": "concentrations", "counts": "counts", "volume": "volume"}}}
```

> The composite specification format will declare which processes are used, the models that they are running, and
> how they are connected through their ports (Figure 3). Since these specifications are just data, they can be easily
> sent between computers, stored for reuse and sharing, and can readily be supported in any programming language.

### 1.4 Orchestration methods

> Orchestration methods that specify how to run the composition. These are like "master algorithms'' that make calls
> to individual processes, and apply their updates to the exposed simulation state variables. Composite simulations
> will read the composite specification, pull down the declared simulators, load in the models, and orchestrate their
> co-simulation according to the orchestration methods. Some examples of orchestration methods as shown in Figure 1C
> include 1) a multi-timestepping discrete event scheduler, which runs each process according to its adjustable
> simulation time step, and 2) a workflow that declares the order dependencies between step processes as a type of
> directed acyclic graph.

And from Aim 3, Task 3.2:

> This will include support for a multi-timestep orchestration method (Fig 1C left), a workflow orchestration method
> (Fig 1C right), and event-driven restructuring in which new processes and states can be added during simulation run
> time.

### 1.5 The exchange format

> The full composition interface protocol will include a format for persistent storage, which can be specified as
> either JSON or XML. A process interface can be declared by stating where the process can be found, an algorithm id,
> and its interface with ports that map to data types and annotations (Figure 2).

### 1.6 Requirements from Aim 3 that bind the protocol

The static checker (Task 3.3):

> Static composite checker. This software will read the composition specification, check that each component is well
> defined, and wired correctly. The type system and annotations of the process ports will check that ports map to the
> right types. The checker will return a list of suggestions to guide users in their composition.

Annotation-based composition (Task 3.3):

> composition can use annotated units to determine whether two processes can connect to the same state. If one is
> mmol/L and the other is mol/L, they cannot directly connect but need an added adapter that converts from one unit
> type to another. Or, if two models connect to proteins that have matching uniProt IDs, then they can be
> automatically connected.

The adapter registry (Task 3.3):

> We will make an adapter registry (like KiSAO but for converting state types) where users can register adapters.
> Their interfaces will require annotations to declare the data types they convert between. Adding adapters to a
> composite simulator can be done semi-automatically, by having the composite checker read the annotations on the
> ports and suggesting adapters from the registry based on pattern-matching.

Deployment (Task 3.4):

> A composite simulation can include some processes that are run locally via Python API, but also use webservices to
> make calls to processes running on the cloud, or on a university computer cluster.

> However, we need more low-level communication forms that allow for repeated calls. We also want the container
> wrapper to expose all of the methods for the Process Interface.

### 1.7 The grant's own caveat

> Modules need to run independently for short amounts of time, and exchange updates which are applied to shared
> state variables read through the processes' interface. This is the foundation for distributed computation but can
> also introduce communication delays.

---

## 2. What exists today

Pinned commits: `bigraph-schema` @ `8268aa1` (v1.6.0), `process-bigraph` @ `78d1488` (v1.8.4). Paths are relative
to each repository root; `tests.py` is process-bigraph's root test file. Two-layer split: bigraph-schema defines
what a document *is*; process-bigraph defines what it *does* (`process-bigraph/docs/architecture.md`).

### 2.1 Type system and schema language

A type is a dataclass instance subclassing `Node` (`bigraph_schema/schema.py:55`). There is no separate grammar
file; the schema language is a PEG grammar defined inline in `bigraph_schema/parse.py:35-64`. A schema may be written
three ways, all normalized by `Core.access` (`bigraph_schema/core.py:523`): a string (`'float'`, `'map[float]'`,
`'tuple[integer,float]'`, `'union[...]'`, `'maybe[T]'`, `'overwrite[T]'`, `'a:float|b:string'`, `'float{5.5}'` for
a default, `'float[fg]'` for a unit), a dict with `_type` and structural `_`-keys, or a `Node` instance. Built-in
base types are listed in `schema.py:716-764`. Third-party types and edges are discovered from installed packages
(`bigraph_schema/package/discover.py`), registered under both the fully qualified name and a first-wins short name.

Two facts matter for the protocol. First, an unregistered bare symbol such as `length/time` is **returned as an
opaque string** by the parser rather than rejected (`parse.py:249`); it is carried, not checked. Second, the
per-type behaviours the grant would call "how an update is applied" are not keys on the schema; they are
multiple-dispatch methods on the node class in `bigraph_schema/methods/` (`apply`, `check`, `validate`, `serialize`,
`realize`, `resolve`, `reconcile`, `divide`, and others). Keys such as `_apply`, `_check`, `_description`, `_meta`
do not exist.

Normative examples: `bigraph-schema/tests.py::test_serialize`, `::test_realize`, `::test_resolve`, and the type by
method matrix in `bigraph-schema/test_matrix.py`.

### 2.2 The process and step contract

Class chain: `bigraph_schema.edge.Edge` → `process_bigraph.composite.Open`
(`process_bigraph/composite.py:401`) → `Step` (`:570`) and `Process` (`:777`) → `Composite` (`:1252`), which is
itself a `Process`.

What a wrapper author implements (`bigraph_schema/edge.py`):

| Member | Contract |
|---|---|
| `config_schema` | class attribute, a schema; the document's `config` is validated against it at realization and filled with defaults in `Edge.__init__` |
| `initialize(config)` | the constructor extension point (`edge.py:100`); `__init__` requires a `core` |
| `initial_state()` | seed values for shared stores (`edge.py:104`); conflicting seeds across edges raise at composite initialization (`composite.py:1394-1415`) |
| `inputs()`, `outputs()` | `{port: type}` schemas (`edge.py:113`, `:122`); `interface()` returns exactly `{'inputs', 'outputs'}` (`:144`) |
| `update(state, interval)` | `Process`: returns an update dict keyed by output port (`composite.py:804`); `Step`: `update(state)`, invoked with interval −1.0 (`:762`) |
| `calculate_timestep(interval, state)` | `Process` may shrink its own step (`:801`); non-advancing values raise |
| `triggers()`, `scatter_port()` | `Step` extras: which inputs re-trigger (`:621`); per-match invocation (`:634`) |
| `results()` / `finalize()` | duck-typed step hooks that return a *handle* at end of run (`composite.py:3064`) |

The remote-call vocabulary is defined once, on `Open` (`composite.py:402-406`):

```python
METHOD_COMMANDS = ('initial_state', 'inputs', 'outputs', 'update')
ATTRIBUTE_READ_COMMANDS = ('config', 'schema', 'state')
```

A write-command tuple is referenced in a docstring but commented out (`composite.py:456`, `:515`).

**What `update` returns.** The framework does not define an "update kind". The dict a process returns is projected
through its output wires (`composite.py:1204`) and merged into state by the port type's `apply`
(`bigraph_schema/methods/apply.py`): a numeric atom accumulates (`state + update`), a string overwrites, a
`map`/`list`/`tree` honours the structural sentinels `_add`, `_remove`, and (`map` only) `_divide`. A port typed
`overwrite[T]` replaces instead of accumulating. So whether an update is a delta or a snapshot is a property of the
port's type, not of the process. The three sampled wrappers use all three styles: absolute snapshots under
`overwrite[...]` on every port (`pbg_vcell_fvsolver/processes.py`), deltas computed as `new − old`
(`spatio_flux/processes/dfba.py`), and a mixture of index-scatter lists, `{"set": …}` directives, and scalar
overwrites (one whole-cell step, not examined further). All three are legal today.

Normative examples: `tests.py:70 test_process` (a bare process; the update is a delta), `tests.py:152
test_step_initialization`.

### 2.3 The composite document

The on-disk document is exactly the constructor argument: `Composite.load` is `json.load` followed by construction
(`composite.py:1522`), and the accepted top-level keys are `Composite.config_schema` (`composite.py:1259`):
`schema`, `state`, `interface`, `bridge`, and a handful of engine flags. There is no top-level `emitter`,
`interval`, or `global_time` key; `global_time` is a `float` store injected into `state` if absent
(`composite.py:1322-1333`), and emitters are ordinary `step` nodes. `Composite.save` writes `{'state', 'schema'}`
with no version stamp (`composite.py:2097`).

A process node inside `state` is realized by `realize_link` (`bigraph_schema/methods/realize.py:605`). Recognized
keys: `_type` (`process` | `step` | `composite`, selecting `ProcessLink`/`StepLink`/`CompositeLink` in
`process_bigraph/types/process.py:35-68`), `address`, `config`, `inputs`, `outputs`, `_inputs`/`_outputs` (schema
overrides resolved against `interface()`), `interval` (`ProcessLink` only, default 1.0, `types/process.py:46`),
`priority` and `_triggers` (`StepLink` only), and `instance` (a live object; if present, construction is skipped).
Any other non-underscore key is stashed as a default. Port keys wired in the document but absent from `inputs()` /
`outputs()` are **silently skipped** in both directions (`bigraph_schema/core.py:1023`, `realize.py:584`).

The canonical minimal document, from `tests.py:85 test_composite`:

```python
Composite({
    'schema': {'increase': 'process[level:float,level:float]', 'value': 'float'},
    'interface': {'inputs': {'exchange': 'float'}, 'outputs': {'exchange': 'float'}},
    'bridge':    {'inputs': {'exchange': ['value']}, 'outputs': {'exchange': ['value']}},
    'state': {
        'increase': {
            'address': 'local:IncreaseProcess',
            'config': {'rate': 0.3},
            'interval': 1.0,
            'inputs':  {'level': ['value']},
            'outputs': {'level': ['value']}},
        'value': 11.11}}, core=core)
```

**Wires.** A wire is a list of path segments, relative to the node's parent (`core.py:1143`). Accepted forms: a
list path `['cell','mass']`; a bare string, coerced to a one-element path; `'..'` to ascend (`schema.py:350`);
`'*'` as a wildcard (`composite.py:1222`; `tests.py:752 test_star_update`); integer segments indexing into arrays;
and a nested dict, which wires *sub-ports* of one declared port to different locations. `spatio-flux` relies on the
last form to scatter a single `map` port across a lattice (`spatio_flux/processes/dfba.py`,
`get_single_dfba_spec`). Unwired ports default to identity wiring `{port: [port]}` (`edge.py:14-20`). The type a
process declares for a port becomes the type of the store it is wired to, via `port_merges` (`realize.py:566`).

**Nesting.** A `Composite` node is written as a process with `address: 'local:Composite'` and a `config` holding the
inner `state` and a `bridge`; its `update` returns a *list* of bridge updates (`composite.py:3384`). A
`bridge.conduits` key is read by the engine (`composite.py:3128` region) but is not declared in `config_schema`,
tested, or documented.

**State in the document.** A document may embed initial state alongside process nodes; embedded state and edge
`initial_state()` are combined and must agree. One large project embeds multi-megabyte numpy structured arrays
using a private JSON encoding; the general tagged codec is `bigraph_schema/json_codec.py` and large arrays can be
externalized to Parquet by `bigraph_schema/methods/bundle.py`.

Normative examples: `tests.py:85 test_composite`, `:131 test_infer`, `:451 test_nested_wires`, `:540
test_grow_divide` (nesting plus division).

### 2.4 Orchestration

**Time-stepping.** `Composite.run(interval)` (`composite.py:2599`, inner loop `_run_inner:2631`) is a synchronous
min-step loop, not an event queue. Each iteration: every due process is invoked eagerly and its deferred update
parked in a `front` table; the loop advances `global_time` by the minimum step any process needs; every parked
update whose time has arrived is collected; `apply_updates` (`:3128`) resolves them, folds their schemas with
`resolve`, combines their states with **one** `reconcile`, and applies the result with **one** `apply`. Concurrent
updates are therefore merged by type, not applied in arrival order (`bigraph-schema/doc/reconcile_audit.md` audits
that merge). Serial and thread-parallel invocation are pinned bit-exact by `tests.py:2317`.

**Steps.** Steps fire by data dependency, not time. `build_step_network` (`composite.py:2320`,
`process_bigraph/scheduling.py:307`) records producers and consumers per store path; after every applied tick,
`trigger_steps` (`:2481`) finds steps downstream of the changed paths and `run_steps` (`:2512`) executes them layer
by layer, one `apply_updates` per layer, until `determine_steps` (`scheduling.py:478`) finds nothing runnable. A
cycle is broken by running the highest-`priority` remaining step. `global_time` is appended to the changed paths
every tick (`composite.py:2694`), which is why emitters fire.

**Dynamic restructuring.** Implemented and tested. A process or step returns `_add`, `_remove`, or `_divide`
inside an ordinary update; `apply` performs the structural change and emits events; the composite realizes only
the added subtrees and patches its process and step indexes incrementally (`composite.py:1784`, `:1852`).
`tests.py:1533 test_dynamic_structure` covers spawn, remove, and rewiring a running process; `:540 test_grow_divide`
covers division five generations deep. There is no `_react` or `_move` sentinel at the apply layer; `_react` exists
only as a proposal in `bigraph-schema/doc/method_api_spec.md`, and Milner-style reaction rules are provided by a
process (`process_bigraph/processes/bigraphical_reactive_system.py`) over `bigraph_schema.assembly`.

Normative examples: `tests.py:186 test_dependencies`, `:252 test_dependency_cycle`, `:819 test_update_removal`.

### 2.5 Addresses and transports

An `address` is `protocol:data`, split on the first colon; a string without a colon is `local`
(`bigraph_schema/schema.py:15 normalize_address`). Resolution is a multimethod on the protocol type
(`bigraph_schema/methods/realize.py:552 load_protocol`). Five protocols exist:

| Prefix | Resolution | Wire protocol | Tests |
|---|---|---|---|
| `local:Name` | `core.link_registry` lookup (`bigraph_schema/protocols.py:46`); depends on what the resolving core has registered | in-process | many |
| `local:!module.Class` | import by dotted path; portable | in-process | `tests/test_address_portability.py` |
| `parallel:Name` | wraps the local class in a forked child (`process_bigraph/protocols/parallel.py`) | pickled `(command, args, kwargs)` over a pipe; commands are `METHOD_COMMANDS` plus `end` | none dedicated |
| `rest:` | `RestProcess` (`protocols/rest.py:46`) | HTTP/JSON: `config-schema` → `initialize` → `inputs`/`outputs` → `update` → `end`, mirrored in `server/rest.py` | `tests.py:2625` |
| `ray:Name` | bound shadow class with a per-core batching runtime (`protocols/ray.py`) | Ray pickle, batched per tick | `tests.py:2564` |
| `git:owner/repo[@ref]#module:callable` | fetch, pin SHA, materialize a venv, bind (`protocols/git.py:83`, `:475`) | newline-delimited JSON on stdin/stdout, the only *written* wire schema | `process_bigraph/tests/test_git_protocol.py` (22 tests) |

The `git:` wire schema, from `process_bigraph/protocols/_git_worker.py`:

```
host -> worker : {"cmd": "init", "config": {...}}
worker -> host : {"ok": true, "interface": {"inputs": {...}, "outputs": {...}}}
host -> worker : {"cmd": "update", "state": {...}, "interval": 1.0}
worker -> host : {"ok": true, "update": {...}}
host -> worker : {"cmd": "interface"}
host -> worker : {"cmd": "end"}
error          : {"ok": false, "error": "..."}
```

The `git:` transport also checks that the resolved edge's ports conform to a declared face
(`protocols/git.py`, `conforms`). No message of any transport is expressed as a bigraph-schema type.

Portability lints for documents exist: `unresolvable_addresses` and `assert_portable_addresses`
(`bigraph_schema/protocols.py:120`, `:142`). A `python:{source}<{package}[{version}]>@{module}` notation appears in
`pbest/dependency_resolution/discovery.py`; it is a pre-processing step that rewrites to the registry-dependent
`local:` form and is not understood by either library.

### 2.6 Results

Two mechanisms. An **emitter** is a `Step` whose inputs are whatever the document asks it to observe and whose
`update` returns nothing (`process_bigraph/emitter.py:518`); it fires each tick because `global_time` changed;
results are read back with `gather_emitter_results` (`emitter.py:422`). Separately, any step may implement
`results()` or `finalize()`; `Composite.finalize` (`composite.py:3064`) calls them at end of run and writes the
returned **handle**, never the data, to the step's `results` output. A consumer wired to that handle fires on the
next run by design (`composite.py:3121`). Ecosystem practice adds a third answer: a project may skip emitters and
use dedicated listener steps as first-class nodes.

Normative examples: `tests.py:3292 test_the_results_handle_is_a_reference_not_the_data`; `docs/emitters.md`.

### 2.7 Contracts, units, translators, checks

**Contracts.** `ProcessContract` (`bigraph_schema/contract.py:89`) attaches prose semantics, symbols, assumptions,
and references to a process; its `face` is the machine-checkable typed port core. `Amendment` (`:52`) allows
`narrow` or `annotate`, never `extend`, so a contract only gets stricter as it flows through composition
(`amend:207`). There is no field for an ontology identifier, a KiSAO term, a UniProt id, or provenance on a type or
store; `symbols`, `references`, and `annotate` are free-form.

**Units.** Three mechanisms coexist. A number type may carry a unit as metadata, `float[fg]`, `array[float[fg]]`
(`schema.py:100`); values stay plain floats. A `Quantity` type carries pint quantities at runtime (`schema.py:550`).
On the precompiled fast path, `_compute_unit_scale` (`core.py:1214`) computes a conversion factor between a port's
unit and the store's unit; **if the units are incompatible, pint raises and the caller catches it and uses 1.0**
(`core.py:1278`, `:1484-1489`). The docstring says this "should ideally surface as a wire validation error". The
plain (non-precompiled) view path applies no scaling at all. Dimension strings such as `substance/length^3` are
rendered by `bigraph_schema/units.py:50` but are not registered as types in this repository. Of the three sampled
wrappers, only the whole-cell project types its ports with units.

**Translators.** A `Translator` (`bigraph_schema/translator.py:51`) is a declared, registered crossing between two
schema types returning `Crossed` or `Refusal`, never a silent coercion (`core.py:248`, `:281`). This is the
nearest existing thing to the grant's "adapter", but it is a type-level function, not a process node, and there is
no registry of them beyond the core's own table.

**Checks.** Four partial checkers exist, none of which reads a document and returns suggestions: `validate`
(schema against state, raising); `face_conforms` and `contract_admits` (`bigraph_schema/assembly.py:786`, `:764`)
for filling a site; the address portability lints; and a language server for a DSL in `process-bigraph-lang` whose
grammar is the only description of that DSL.

### 2.8 Serialization, templates, versioning

`Core.serialize` and `Core.realize` round-trip state; `render` and `access` round-trip schemas. A **template** is a
document containing `{"_type": "site", "_sort": …}` nodes; `fill_sites` (`assembly.py:967`) substitutes by path;
`Composite` refuses to construct while a required site is open (`composite.py:2752`). `CompositeSpec`
(`process_bigraph/composite_spec.py`) is a separate authoring descriptor with its own `emitters:` list and
`${name}` substitution; lowering it onto sites was attempted and abandoned (`docs/architecture.md` §8).

Versioning: `process-bigraph` exposes `__version__` guarded by `tests.py:5910`; `bigraph-schema` has no
`__version__`; neither repository has a CHANGELOG; no document, schema, or saved state carries a format version.
The one thing `architecture.md` calls "a wire format" is the content-addressed artifact id
(`process_bigraph/artifacts.py:106`), pinned by golden vectors.

Normative examples: `tests.py:3668 test_unfilled_required_site_is_rejected`; `bigraph-schema/tests.py::
test_fill_admits_a_conforming_filler` and `::test_fill_rejects_an_under_providing_filler`.

---

## 3. Grant vocabulary to code vocabulary

| Grant / paper term | Code identifier | Defining file |
|---|---|---|
| process | `Process` (← `Open` ← `Edge`) | `process_bigraph/composite.py:777`; `bigraph_schema/edge.py` |
| step process (DAG node) | `Step` | `process_bigraph/composite.py:570` |
| state, shared state variable | a store: any non-edge node in `state`; there is no `Store` class | `bigraph_schema/schema.py` |
| port | a key in the `inputs()` / `outputs()` schema; `Link._inputs` / `_outputs` | `bigraph_schema/edge.py:113`, `schema.py:300` |
| wire | a `Wires` tree with `Path` leaves, relative to the link's parent | `schema.py:283`, `:279`; `core.py:1143` |
| interface | `Edge.interface()`; in assembly, a *face* | `edge.py:144`; `assembly.py:57` |
| composite specification | the document `{schema, state, interface, bridge, …}` | `process_bigraph/composite.py:1259` |
| exchange format | `.pbg` JSON; `Composite.save` `{state, schema}`; `.omex` bundle | `composite.py:1522`, `:2097`; `pbest/CLAUDE.md` |
| orchestration: multi-timestep | `Composite.run` / `_run_inner` front loop | `composite.py:2599`, `:2631`; `scheduling.py:257` |
| orchestration: DAG workflow | step network | `composite.py:2320`, `:2512`; `scheduling.py:307`, `:478` |
| event-driven restructuring | sentinels `_add`, `_remove`, `_divide` | `bigraph_schema/methods/apply.py` |
| adapter process | *absent as a concept*; nearest: `Translator` (type level) | `bigraph_schema/translator.py:51` |
| adapter registry | *absent* | — |
| process_location | `address` | `schema.py:15` |
| update_method (KiSAO id) | *absent* | — |
| annotation (units) | `Number._units`; `Quantity` | `schema.py:100`, `:550` |
| annotation (semantics, provenance) | `ProcessContract`; `Amendment` (`narrow`, `annotate`) | `contract.py:89`, `:52` |
| static composite checker | *absent as one tool*; partial: `validate`, `face_conforms`, portability lints, DSL LSP | `assembly.py:786`; `protocols.py:120` |
| template | a document containing `Site` nodes | `process_bigraph/templates.py`; `assembly.py:967` |
| site (hole) | `Site` with `_sort` | `schema.py:630` |
| ground (runnable) | `is_ground_document`; `_require_ground_document` | `templates.py:122`; `composite.py:2752` |
| face | typed port core of a contract; `face_conforms` | `contract.py`; `assembly.py:786` |
| contract | `ProcessContract` | `contract.py:89` |
| bridge (nesting) | `bridge` and `interface` keys | `composite.py:1259`; `tests.py:85` |
| emitter, results | `Emitter(Step)`; `results()` / `finalize()` handle | `emitter.py:518`; `composite.py:3064` |
| protocol (address sense) | `local`, `parallel`, `rest`, `ray`, `git` | `bigraph_schema/protocols.py`; `process_bigraph/protocols/` |
| protocol (remote-call sense) | `Open.METHOD_COMMANDS`; the `git:` newline JSON | `composite.py:402`; `protocols/_git_worker.py` |
| update (a process's return) | dict projected by output wires, merged by `reconcile` then `apply` | `composite.py:1204`, `:3128` |
| adjustable time step | `ProcessLink.interval`; `calculate_timestep` | `types/process.py:46`; `composite.py:801` |
| XML serialization | *absent* | — |

---

## 4. Decisions

Each block has the same five fields. *Grant said* quotes §1. *Code does* cites §2. *Why they differ* records only
what the written record shows; where the record is silent it says so. *Options* lists two to four choices with who
pays. *Your call* is left blank.

### D-A. Declared ports versus wired ports

**Grant said.** "The ports for all processes that share a state need to match, with the same data type and
annotations."

**Code does.** A process declares ports in `inputs()` / `outputs()`; a document wires ports by name. Keys wired but
not declared are silently skipped (`core.py:1023`, `realize.py:584`). Three ecosystem practices exploit or collide
with this: sub-port scatter, where one declared `map` port is wired as a dict of per-key paths to different stores
(`spatio-flux`); double listing, where a port declared only as an input is also placed under `outputs` to make it
read-modify-write; and synthetic ordering ports (`_layer_in_N` → `_layer_out_N`) that appear in documents but in no
`inputs()`, used to force step execution order in one large project. A validator that checked wired ⊆ declared
would reject every node in that project's documents.

**Why they differ.** The record does not show a decision; the skip behaviour is an implementation convenience that
practices then grew around.

**Options.**
1. Wired ⊆ declared, strictly; synthetic ordering ports become a declared step-ordering mechanism. Costs: document
   rewrites where synthetic ports are used (document authors); `realize_link` errors instead of skips (engine).
2. Declared ⊆ wired: a document may wire extra ports, typed by the store they reach. Costs: a contract cannot be
   verified from `inputs()` alone (tooling, any checker).
3. Two tiers: declared ports are the contract; a reserved underscore-prefixed namespace is engine-owned and exempt.
   Costs: the spec must define the namespace (spec authors); lints must know it (tooling).
4. Status quo, documented as "undeclared keys are ignored". Costs: none now; every checker stays unsound.

**Your call.**

### D-B. What an update is

**Grant said.** Processes "exchange updates which are applied to shared state variables".

**Code does.** The framework has no notion of update kind. A returned dict is merged by the port type's `apply`:
numeric atoms accumulate, strings overwrite, containers honour `_add`/`_remove`/`_divide`, and `overwrite[T]` opts a
port out of accumulation (§2.2). Sampled wrappers return absolute snapshots, deltas, and mixed structural
directives, all legal.

**Why they differ.** The grant's "updates … applied" is compatible with any of these; the code chose to make the
question a property of types, and `README.md` describes the result as "typed deltas merged by the runtime", which
describes the numeric default rather than a rule.

**Options.**
1. The protocol says nothing; `apply` per port type decides. Costs: a wrapper author must read the port type to
   know what to return (wrapper authors); no checker can validate an update against a declaration (tooling).
2. Each output port declares `delta` | `overwrite` | `structural` in its type. Costs: every wrapper's `outputs()`
   is touched (wrapper authors); a type wrapper per kind (engine).
3. The protocol fixes "an update is a delta" and forbids snapshots; replay-style processes must diff. Costs: the
   snapshot-style wrappers (wrapper authors); `overwrite[…]` loses its role.

**Your call.**

### D-C. The scheduling contract

**Grant said.** "a multi-timestepping discrete event scheduler, which runs each process according to its adjustable
simulation time step".

**Code does.** A `Process` has an `interval` in the document (`types/process.py:46`) and may adapt it through
`calculate_timestep` (`composite.py:801`). The loop that runs it is a min-step front loop, not an event queue, and
concurrent updates are reconciled into one (§2.4). A `Step` has no interval and is invoked with −1.0. Separately,
one large project puts `interval: null` on its step nodes, which the engine ignores, and gates each step with a
project-level condition that the core does not define; the core's own duck-typed skip hook is `perform_update()`.

**Why they differ.** The observable behaviour, each process advancing on its own step, matches the grant. The
mechanism differs, and the record shows no discussion of whether merge-by-type at a shared tick, rather than
ordered event application, was a deliberate choice.

**Options.**
1. Specify the observable contract only: each process advances by its own (possibly adaptive) interval; updates due
   at the same time are merged by type. Costs: none to the engine; the spec must state that ordering is undefined
   (spec authors, wrapper authors who assumed order).
2. Additionally standardize self-gating for steps through the existing `perform_update()` hook. Costs: projects
   using their own gate migrate (document authors); the hook moves from duck-typed to declared (engine).
3. Specify an event-queue semantics as written and change the engine. Costs: rewrite of `_run_inner` and
   `apply_updates`; loses the one-reconcile-per-tick property and the serial/parallel bit-exactness test (engine).

**Your call.**

### D-D. Units on ports

**Grant said.** Ports carry "annotations such as units"; "If one is mmol/L and the other is mol/L, they cannot
directly connect but need an added adapter".

**Code does.** A port may carry a unit as type metadata (`float[fg]`); on the precompiled path a conversion factor
is computed with pint, and an **incompatible pair silently becomes 1.0** (`core.py:1278`, `:1484-1489`); the plain
path applies no scaling. Only one sampled wrapper types its ports with units; the others record units in prose or
in a `TODO`.

**Why they differ.** The docstring at `core.py:1224` records the intent that a mismatch "should ideally surface as a
wire validation error"; it was deferred.

**Options.**
1. Units are documentary (`float[fg]`) and never enforced. Costs: the silent 1.0 stays; unit bugs surface in
   results (document authors).
2. A unit mismatch on a wire is a realization error; conversion happens only through an explicit adapter process.
   Costs: remove the fallbacks (engine); every unit-typed wrapper must match its stores (wrapper authors).
3. Auto-convert compatible dimensions, error on incompatible ones, on both view paths. Costs: pint on the hot path
   and parity work between the two paths (engine).
4. Runtime `Quantity` values on ports. Costs: every wrapper handles pint objects (wrapper authors); tagged
   serialization everywhere (engine, tooling).

**Your call.**

### D-E. Semantic annotations on ports and processes

**Grant said.** "a formal ontology developed with TR&D 2 that will include annotations such as units, semantics,
and provenance"; "if two models connect to proteins that have matching uniProt IDs, then they can be automatically
connected"; Figure 2 places a KiSAO id on every process.

**Code does.** No ontology, identifier, or provenance field exists on a type, port, or store. `ProcessContract`
attaches free-form `symbols`, `references`, and `annotate` amendments to a process (`contract.py:89`). Nothing
matches ports by identifier.

**Why they differ.** The record shows no TR&D2 ontology delivered to this code base; the contract mechanism was
built for prose semantics and monotone narrowing, not for identifiers.

**Options.**
1. Annotations stay in `ProcessContract` as free text; no identifiers on ports. Costs: annotation-based composition
   is out of scope (grant reporting).
2. Add an optional `_annotations` map (CURIE → value) to any node type, carried but not interpreted. Costs: schema
   key, serialization, render (engine); nothing for wrappers until they opt in.
3. As 2, plus the checker uses matching identifiers to propose wires and unit adapters. Costs: a matching rule and
   an identifier vocabulary agreed with TR&D2 (spec authors, tooling).

**Your call.**

### D-F. Adapters and the checker as protocol concepts

**Grant said.** "Adapter processes that can translate between data types will play an important role"; "an
adapter registry (like KiSAO but for converting state types)"; a checker that "will return a list of suggestions".

**Code does.** Adapters exist as ordinary processes written by hand and as type-level `Translator`s (§2.7);
there is no registry category for them, though `viva-catalog` indexes processes by tag. Four partial checkers
exist and none reads a document and returns suggestions (§2.7).

**Why they differ.** The record shows the checker and registry deferred behind the engine and the wrappers; the
`Translator` design explicitly contrasts itself with silent coercion but does not mention a registry.

**Options.**
1. Adapters and the checker are tooling, outside the protocol. Costs: the protocol cannot promise automatic
   composition (grant reporting); nothing else.
2. The protocol defines an *adapter* as a process whose contract declares a `from` and `to` type, and a registry as
   any index that can be queried by that pair. Costs: a contract field (engine); tagging existing adapters
   (wrapper authors); `viva-catalog` gains the query (tooling).
3. As 2, plus a specified checker output format (a list of findings with a suggested adapter per unit mismatch).
   Costs: the checker itself, and its integration with the LSP and portability lints (tooling).

**Your call.**

### D-G. How a model artifact travels with a document

**Grant said.** The composite specification "will declare which processes are used, the models that they are
running"; Figure 3 carries `"config": {"model": "sbmlfile1"}`.

**Code does.** Three incompatible conventions. Inline: the model source is a string in `config` (Antimony in
`pbg_vcell_fvsolver`). Path: `config.model_file` is a string that may be a built-in model name or a file path,
disambiguated by substring; `pbest` relocates into the `.omex` any config string that names an existing file and
rewrites it to a bare filename (`pbest/execution/remote/utils.py`, `_normalize_pbg_paths`). Upstream step: a step's
outputs are wired into downstream processes' *config* slots, so the model is produced at run time (one large
project). There is no `path` type; the comment `# TODO -- register a "path" type` marks the gap (`spatio-flux`).

**Why they differ.** Each convention solved one wrapper's problem; the file-existence heuristic decides which one a
document gets without the author saying.

**Options.**
1. A `path` type in bigraph-schema; only `path`-typed config values are relocated into `.omex`. Costs: new type and
   a rewrite of the relocation step (engine, pbest); wrappers retype `model_file` (wrapper authors).
2. Inline models only. Costs: large documents; run-time-produced models impossible (document authors).
3. Upstream-step-into-config as the sanctioned pattern, with config-slot wiring made a first-class site kind.
   Costs: template spec text (spec authors); builder steps for every model (wrapper authors).
4. All three allowed, each named and detected by type rather than by file existence. Costs: spec text plus a lint
   (tooling).

**Your call.**

### D-H. Address grammar and resolution

**Grant said.** A process interface "can be declared by stating where the process can be found"; Figure 2 uses
`"process_location": "URI …"`; Figure 3 uses `"process_id": ["Tellurium", "v2.2.3"]`.

**Code does.** `address` is `protocol:data`; five protocols exist (§2.5). `local:Name` depends on what the resolving
core has registered and fails elsewhere; `local:!module.Class` is portable; `git:` pins a commit. Nothing carries a
version except `git:` by ref. `pbest`'s `python:` notation is not understood by either library.

**Why they differ.** The registry form came first for convenience; portability was added later as lints rather
than as a rule (`bigraph-schema/doc/address_portability_and_discovery.md` scopes three escalating levels, of which
the first shipped).

**Options.**
1. The standard names exactly the five protocols and their grammars; `local:Name` is allowed but documents using it
   are marked non-portable by the lint. Costs: spec text; nothing else.
2. As 1, but a shared document must use a portable form (`local:!…` or `git:`), enforced at realization.
   Costs: rewriting registry-form addresses in shared documents (document authors); an engine flag.
3. Add a version-bearing form (package plus version plus entry) to the grammar, subsuming `pbest`'s notation.
   Costs: grammar, resolver, and environment materialization for a non-git source (engine, pbest).

**Your call.**

### D-I. The remote process interface

**Grant said.** "It will support distributed, network-based communication using a remote procedure call"; processes
"will only be required to send structured messages in response to queries about their ports and variable types,
parameters, initial state, annotations, and the update function"; "the container wrapper to expose all of the
methods for the Process Interface".

**Code does.** The vocabulary exists once, on `Open` (`composite.py:402`): four method commands and three
attribute reads. Four transports carry some or all of it in four different encodings; only `git:` has a written
message schema, and none of the messages is typed with bigraph-schema (§2.5). No transport exchanges annotations.

**Why they differ.** Each transport was built for a deployment need (multiprocessing, HTTP, Ray, foreign venv); the
common vocabulary was factored out on the Python side but never written down as a wire contract.

**Options.**
1. `METHOD_COMMANDS` plus `end` is the normative vocabulary; every transport must carry exactly those; the message
   schema is written once. Costs: audit of the REST routes, the Ray batch actor, and the pipe transport (engine).
2. Only the `git:` newline JSON is normative; the others are implementation detail. Costs: users of `rest:` and
   `ray:` get no guarantees (deployers, tooling).
3. Transports are out of scope; the protocol ends at the Python `Edge` contract. Costs: the grant's RPC promise is
   recorded as dropped (grant reporting).

**Your call.**

### D-J. The document envelope, its schema, and results

**Grant said.** "a format for persistent storage, which can be specified as either JSON or XML"; specifications
"are just data".

**Code does.** The document is the constructor argument; there is no JSON Schema for it anywhere, no format version
field, no version in `Composite.save` output, and no CHANGELOG in either repository (§2.3, §2.8). `bridge.conduits`
is used but undeclared. Large embedded arrays use a private encoding. Results reach the outside through an emitter
step, a `results` handle, or project-specific listener steps (§2.6).

**Why they differ.** The format was never frozen because the engine and the document evolved together; the
`pbg-template` workspace validates studies and investigations with JSON Schema but never the composite itself.

**Options.**
1. Publish a JSON Schema for the document as it is, add a `format_version` key, declare `conduits`. Costs: the
   schema and a version bump discipline (engine, tooling); nothing for wrappers.
2. As 1, plus results emission is standardized on the emitter step; listener steps are a project convention.
   Costs: none to the engine; projects using listeners are out of spec (document authors).
3. As 1, plus the `results()` handle is the only standard result surface and emitters are a convenience. Costs:
   emitter users add a flush step (document authors).

**Your call.**

### D-K. Replay processes

**Grant said.** "Modules need to run independently for short amounts of time, and exchange updates".

**Code does.** Nothing prevents a process from pre-running its whole simulation at construction and streaming
cached snapshots from `update`, ignoring upstream writes entirely; `pbg_vcell_fvsolver/processes.py` does exactly
that and documents it. The core cannot tell such a process from a reactive one.

**Why they differ.** A batch solver with a high start-up cost is easier to wrap this way; the protocol has no word
for the trade-off.

**Options.**
1. Name the class ("replay" or "non-reactive") in the contract so a checker can warn when a replay process is wired
   to receive inputs. Costs: a contract flag (engine); tagging (wrapper authors).
2. Forbid it: a process must honour its inputs each update. Costs: the batch-solver wrappers rewrite or are
   excluded (wrapper authors).
3. Say nothing. Costs: silent non-coupling in composites that look coupled (document authors).

**Your call.**

### D-L. Which artifact is the exchange format

**Grant said.** Figure 3: a `processes` map with `process_id` and `config`, and a separate `wires` map.

**Code does.** The raw document (`{schema, state, interface, bridge}`) is what `Composite.load` reads and what
`.pbg` files contain. `CompositeSpec` is a separate authoring descriptor, YAML-first, with identity, an `emitters:`
list, and `${name}` parameters; 93 YAML composites across the ecosystem use it, and it is lowered into a raw
document before construction. Figure 3's shape is closer to `CompositeSpec` than to the raw document.

**Why they differ.** The raw document is what the engine needs; the descriptor is what authors want to write; the
record shows the two were reconciled by lowering rather than by choosing.

**Options.**
1. The raw document is the format; `CompositeSpec` is an authoring tool. Costs: a JSON Schema for the raw document
   (tooling); Figure 3's shape is abandoned.
2. `CompositeSpec` is the format; raw documents are a compiled form. Costs: `Composite.load` parity is lost; two
   schemas to maintain (engine, tooling).
3. Both, with a declared lowering from descriptor to document and a version stamp on each. Costs: the lowering
   specification and its tests (engine); two schemas maintained.

**Your call.**

### D-M. Nesting and the bridge

**Grant said.** Nothing explicit; the Figure 1 caption speaks of processes and states at one level.

**Code does.** A `Composite` is a `Process`; a nested composite exposes an `interface` and maps it to inner stores
through `bridge` wires (`tests.py:85`); its `update` returns a list of bridge updates; the `conduits` key routes
structural sentinels outward without instantiating daughters inside the mother (`composite.py:3128` region).
Division-based multi-cell models depend on this.

**Why they differ.** Hierarchy came from the paper's bigraph formalism and from whole-cell and colony use; the grant
text predates it.

**Options.**
1. Nesting, `interface`, and `bridge` are part of the standard; `conduits` is declared and tested. Costs: spec text;
   declaring and testing `conduits` (engine).
2. Nesting is an engine feature outside the protocol; a shared document is flat. Costs: multi-cell documents
   cannot be exchanged as written (document authors).

**Your call.**

### D-N. Ownership and home

**Grant said.** The CIP would be "established early and expanded as needed" and integrated "into community
standards".

**Code does.** The protocol is described by the paper's supplement (not in any checkout), by ten design documents
of varying status across two repositories, and by this review. None is versioned as a specification; nothing has
been presented to COMBINE.

**Why they differ.** The code moved faster than a written standard, and the paper absorbed the role of
specification at publication time.

**Options.**
1. The paper's supplement is the specification; this review becomes an errata and decisions list against it.
   Costs: the supplement must be obtained, versioned, and reconciled with 1.6.0 / 1.8.4 (spec authors).
2. A new `cip-spec` document (repo to be chosen) is the specification, derived from the code at pinned commits,
   citing the paper for semantics. Costs: writing and maintaining it; a release discipline tied to the two
   packages (spec authors, engine).
3. `process-bigraph/docs/architecture.md` is promoted to the specification and extended with §2 of this review.
   Costs: that document's owner takes on the protocol (engine maintainers); this repository's draft moves.

Where the draft lives now is `compose-api/docs/cip/`; moving it into a `vivarium-collective` repository is not to
be done without the user's explicit go-ahead.

**Your call.**

### Set aside

Two grant-era elements are recorded here so they are not lost, and deliberately not opened as decisions:

- **KiSAO algorithm id on the process interface** (Figure 2's `update_method`). No field exists; nothing in the
  ecosystem reads one. If D-E adopts identifiers on nodes, this becomes one identifier among others.
- **XML serialization.** Only JSON exists. The grant offered "either JSON or XML"; the ecosystem chose JSON
  everywhere, including the `.omex` bundle contents.

---

## Appendix A. Normative examples

process-bigraph `tests.py` unless noted.

| Semantic | Test |
|---|---|
| bare process contract; update is a delta | `:70 test_process` |
| document shape with `interface` and `bridge`; nested update returns a list | `:85 test_composite` |
| minimal state-only document | `:131 test_infer` |
| step node, `run_steps_on_init`, chained ordering | `:152 test_step_initialization` |
| step DAG layering, exact numeric result | `:186 test_dependencies` |
| cycle breaking and ordering | `:252 test_dependency_cycle` |
| composite as process, bridge-only output | `:451 test_nested_wires` |
| nesting plus division five generations deep | `:540 test_grow_divide` |
| wildcard wires | `:752 test_star_update` |
| `_remove` structural update | `:819 test_update_removal` |
| spawn, remove, rewire at run time | `:1533 test_dynamic_structure` |
| serial and parallel invocation are bit-exact | `:2317 test_parallel_processes_matches_serial` |
| REST transport round trip | `:2625 test_rest_server_initialize_inputs_outputs_update` |
| results handle is a reference, not data | `:3292 test_the_results_handle_is_a_reference_not_the_data` |
| required site rejected | `:3668 test_unfilled_required_site_is_rejected` |
| version guard | `:5910 test_version_matches_pyproject` |
| `git:` interface, update, conformance | `process_bigraph/tests/test_git_protocol.py` |
| schema language forms | bigraph-schema `tests.py::test_serialize`, `::test_realize`, `::test_render` |
| wiring compatibility | bigraph-schema `tests.py::test_resolve`, `::test_resolve_conflict`, `::test_unify` |
| structural subtyping of faces | bigraph-schema `tests.py::test_fill_admits_a_conforming_filler`, `::test_fill_rejects_an_under_providing_filler` |
| contract monotonicity | bigraph-schema `tests.py::test_narrow_is_monotone`, `::test_extend_is_refused` |
| address portability lints | bigraph-schema `tests/test_address_portability.py` |

## Appendix B. Sources and anchors

**Grant text.** `docs/grant/trd3/TR&D3 - Research Strategy.md` (Aim 2, Aim 3 Tasks 3.2–3.4, Figure captions);
`TR&D3 - Specific Aims.md`. Git-ignored in this repository.

**Repositories at the cited commits.** `vivarium-collective/bigraph-schema` @ `8268aa1` (v1.6.0);
`vivarium-collective/process-bigraph` @ `78d1488` (v1.8.4). Ecosystem samples: `vivarium-collective/spatio-flux`,
`vivarium-collective/pbg-vcell-fvsolver` (as `viva-vcell-fvsolver`), `CovertLabEcoli/sms-ecoli` (one node only),
`biosimulations/pbest` (`CLAUDE.md`, `execution/remote/utils.py`, `dependency_resolution/discovery.py`),
`vivarium-collective/pbg-template` (the three workspace schemas), `biosimulations/process-bigraph-lang` (the DSL
grammars).

**Existing design documents.** Listed in §0; none restated here.

**Paper.** Agmon, E. and Spangler, R. K., "Process Bigraphs and the Architecture of Compositional Systems Biology",
arXiv:2512.23754 (submitted 2025-12-27). Abstract cited in §0; Supplementary Materials not consulted.

**Anchor verification.** Every `path:line` in §2 and §3 was checked on 2026-09-09 against the two commits above with
`docs/cip/check_citations.py`; the script and its output are part of the review record.
