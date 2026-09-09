# CIP glossary: grant vocabulary to code vocabulary

Companion to [CIP-design-review.md](CIP-design-review.md) §3. Pinned commits: `bigraph-schema` @ `8268aa1`
(v1.6.0), `process-bigraph` @ `78d1488` (v1.8.4). Rows marked *absent* have no code counterpart today.

| Grant / paper term | Code identifier | Defining file |
|---|---|---|
| process | `Process` (← `Open` ← `Edge`) | `process_bigraph/composite.py:777`; `bigraph_schema/edge.py` |
| step process (DAG node) | `Step` | `process_bigraph/composite.py:570` |
| composite simulator | `Composite`, itself a `Process` | `process_bigraph/composite.py:1252` |
| state, shared state variable | a store: any non-edge node in `state`; no `Store` class exists | `bigraph_schema/schema.py` |
| port | a key in the `inputs()` / `outputs()` schema; `Link._inputs` / `_outputs` on the schema side | `bigraph_schema/edge.py:113`, `:122`; `schema.py:300` |
| wire | a `Wires` tree with `Path` leaves, relative to the link's parent node | `schema.py:283`, `:279`; `core.py:1143` |
| interface | `Edge.interface()` → `{'inputs','outputs'}`; in assembly, a *face* | `edge.py:144`; `assembly.py:57` |
| composite specification | the document `{schema, state, interface, bridge, flags}` | `process_bigraph/composite.py:1259` |
| exchange format | `.pbg` JSON; `Composite.save` writes `{state, schema}`; `.omex` bundles a document with its files | `composite.py:1522`, `:2097`; `pbest/CLAUDE.md` |
| orchestration: multi-timestep | `Composite.run` / `_run_inner`, a min-step front loop | `composite.py:2599`, `:2631`; `scheduling.py:257` |
| orchestration: DAG workflow | the step network: `build_step_network`, `determine_steps`, `run_steps` | `composite.py:2320`, `:2512`; `scheduling.py:307`, `:478` |
| event-driven restructuring | update sentinels `_add`, `_remove`, `_divide`; `_react` is a proposal only | `bigraph_schema/methods/apply.py`; `doc/method_api_spec.md` |
| adapter process | *absent as a concept*; nearest: `Translator` (type level, not a node) | `bigraph_schema/translator.py:51` |
| adapter registry | *absent*; `viva-catalog` indexes processes by tag | — |
| process_location | `address`, `protocol:data` | `bigraph_schema/schema.py:15` |
| update_method (KiSAO id) | *absent* | — |
| annotation: units | `Number._units` metadata (`float[fg]`); runtime `Quantity` | `schema.py:100`, `:550` |
| annotation: semantics, provenance | `ProcessContract`; `Amendment` (`narrow` or `annotate`, never `extend`) | `contract.py:89`, `:52`, `amend:207` |
| static composite checker | *absent as one tool*; partial: `validate`, `face_conforms`, `contract_admits`, portability lints, DSL language server | `assembly.py:786`, `:764`; `protocols.py:120`, `:142` |
| template | a document containing `Site` nodes; filled by path | `process_bigraph/templates.py`; `assembly.py:967` |
| site (hole) | `Site`, `{"_type":"site","_sort":…}`; optional if it has a `_default` | `schema.py:630` |
| ground (runnable) | `is_ground_document`; enforced by `_require_ground_document` | `templates.py:122`; `composite.py:2752` |
| face | the typed port core of a contract; checked by `face_conforms` | `contract.py`; `assembly.py:786` |
| contract | `ProcessContract` | `contract.py:89` |
| amendment | `Amendment` | `contract.py:52` |
| bridge (nesting) | `bridge` wires plus `interface` schema on a `Composite` | `composite.py:1259`; `tests.py:85` |
| conduits | `bridge.conduits`, read by the engine, undeclared and untested | `composite.py:3128` region |
| emitter | `Emitter(Step)`; `gather_emitter_results` | `emitter.py:518`, `:422` |
| results | the `results()` / `finalize()` handle, never data | `composite.py:3064` |
| protocol (address sense) | `local`, `parallel`, `rest`, `ray`, `git` | `bigraph_schema/protocols.py`; `process_bigraph/protocols/` |
| protocol (remote-call sense) | `Open.METHOD_COMMANDS` + `ATTRIBUTE_READ_COMMANDS`; the `git:` newline JSON | `composite.py:402`; `protocols/_git_worker.py` |
| update (a process's return) | a dict projected through output wires, merged by `reconcile` then `apply` | `composite.py:1204`, `:3128` |
| adjustable time step | `ProcessLink.interval`; `calculate_timestep` | `types/process.py:46`; `composite.py:801` |
| replay process | *absent as a concept*; a process that pre-runs and streams cached snapshots | `pbg_vcell_fvsolver/processes.py` |
| XML serialization | *absent* | — |
