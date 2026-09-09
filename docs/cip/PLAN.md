# Plan: CIP design review (approved 2026-09-09, tentative)

> Saved verbatim from the planning session so the review record survives outside it. The deliverable it describes
> is `CIP-design-review.md` in this directory.

## Context

The TR&D3 grant's Aim 2 promised a Composition Interface Protocol (CIP): a process interface, a composite
specification ("wiring diagram"), orchestration methods, and a JSON/XML exchange format, all in Year 1. The tracker
records this as `in-spirit` (deviation D1): the protocol exists as running code in `bigraph-schema` 1.6.0 and
`process-bigraph` 1.8.4, an arXiv paper (2512.23754, Agmon & Spangler) whose supplement claims to be the formal
specification, and about ten design documents across the two repos, but there is no single versioned spec and
nothing has gone to COMBINE.

The user wants the spec written, but explicitly **not** as a document that ratifies the grant or the code. They need
to (1) understand what was proposed, (2) see what was actually built, and (3) weigh in on each design decision from
their own experience. The deliverable is therefore a **design review**, not yet a normative standard.

**User decisions:**
- Audience: the user and the TR&D3 team, as a design review; formalize later.
- Location: `compose-api/docs/cip/` for the draft; move to `process-bigraph` or a spec repo once settled.
- Grant weight: present grant and implementation side by side, argue neither, no recommendations unless asked.
- Keep open as decisions: units and semantic annotations on ports (TR&D1/TR&D2); adapter registry and static
  checker as protocol-level concepts. Set aside with one line each: KiSAO id on the interface; XML serialization.
- **Grant dates (corrected by the user):** project period **03/01/2024 – 02/28/2029**. Y1 = Mar 2024–Feb 2025 ·
  Y2 = Mar 2025–Feb 2026 · **Y3 = Mar 2026–Feb 2027 (now)** · Y4 = Mar 2027–Feb 2028 · Y5 = Mar 2028–Feb 2029.
  The tracker's "grant clock" line (`docs/grant/trd3/tracking/TRACKER.md:8-9`) currently says mid-2024 with
  Jul–Jun windows and must be corrected; the due/overdue analysis is unchanged (still Y3).

## Facts the document is built on (from three explorations + reviewer critique)

**Cite, don't restate:** `process-bigraph/docs/architecture.md` §7 (the laws); `bigraph-schema/docs/superpowers/specs/
2026-07-30-template-slot-primitive-design.md` §1, §4.7 (sites, `fill`, groundness, "contract = face + semantics +
amendments"); `bigraph_schema/contract.py` (`ProcessContract`, monotone `Amendment`); `bigraph-schema/doc/
address_portability_and_discovery.md`; `doc/method_api_spec.md` and `doc/reconcile_audit.md`; `process-bigraph/docs/
superpowers/specs/2026-07-31-git-remote-protocol-design.md`; `docs/concepts/composites-and-templates.md`; the arXiv
abstract's claim that its Supplementary Materials "provides the formal specification" (supplement not in any checkout).

**Unoccupied ground the document fills:**
1. No JSON Schema or normative statement of a `.pbg` composite document exists; de-facto definition is one sentence
   in `pbest/CLAUDE.md`. `pbg-template` validates studies/investigations/workspace, never composites.
2. No rule reconciling declared ports (`inputs()`/`outputs()`) with wired ports. `realize_link` silently skips
   undeclared keys (`core.py:1023`). v2ecoli wires synthetic `_layer_in_N`/`_layer_out_N` ports no `inputs()`
   declares; spatio-flux scatters one map port to many paths; v2ecoli lists `global_time` in both `inputs` and
   `outputs` to fake an inout port.
3. `update()` return is interpreted by the port type's `apply` (numeric accumulates, string overwrites, containers
   honour `_add`/`_remove`/`_divide`); `overwrite[T]` opts out. The three wrappers (snapshot / delta / mixed
   directives) are all legal because **there is no rule**, not because they violate one.
4. Three incompatible model-artifact conventions: inline Antimony string in config; `model_file` string overloaded
   as built-in-name-or-path (pbest `_normalize_pbg_paths` relocates it only if it names an existing file); an
   upstream `InitializeStep` whose outputs are wired into downstream *config slots*.
5. Units: `Number._units` metadata (`float[fg]`), runtime `Quantity`, and compile-time wire scaling via pint; an
   incompatible pair **silently falls back to scale 1.0** (`core.py:1228-1232`, `1278`, `1484-1489`), only on the
   precompiled path; only v2ecoli types its ports with units.
6. No semantic annotation mechanism on types or ports (no KiSAO/SBO/UniProt/CURIE field). Hooks: `ProcessContract`
   `symbols`/`references` and `annotate` amendments, all free-form.
7. Address grammar: `local:<name>` (registry-dependent), `local:!module.Class` (portable), `parallel:`, `rest:`,
   `ray:`, `git:<owner>/<repo>[@<ref>]#<module>:<callable>`. pbest's `python:{source}<{pkg}[{ver}]>@{module}` is a
   pre-processing notation that never reaches either library and rewrites to the *registry-dependent* `local:` form.
8. No document envelope version; `Composite.save` writes `{'state','schema'}` unstamped; no CHANGELOG in either
   repo; `bigraph-schema` has no `__version__`. `process-bigraph` has `__version__` guarded by a test. Artifact ids
   (`artifacts.py:106`) are the one declared wire format, with golden vectors.
9. Results: emitter `Step` nodes (`local:ram-emitter`), library-side plotting over emitter output, or dedicated
   listener Steps (v2ecoli). `results()`/`finalize()` (`composite.py:3064`) is a real protocol hook returning a
   handle, never data; a `results` consumer fires on the *next* run by design.
10. Scheduling: `interval` on a `ProcessLink` (`types/process.py:47`) plus `calculate_timestep`; v2ecoli steps carry
    `interval: null` (ignored; steps are invoked with −1.0) and gate themselves with `update_condition()`, which is
    **not** a core hook (the core's duck-typed hook is `perform_update()`). Must verify whether `EcoliStep` maps one
    to the other before the document cites it.
11. A "replay" process class exists (vcell-fvsolver pre-runs the full solve and streams snapshots, ignoring upstream
    writes) that the protocol neither names nor forbids.
12. Process contract: `Edge` → `Open` → `Process`/`Step` (`composite.py:401,570,777`); `Composite` is a `Process`
    (`:1252`). `Open.METHOD_COMMANDS = ('initial_state','inputs','outputs','update')` is the only formal remote
    vocabulary; `parallel:` rides it; `rest:` has an implicit URL/JSON contract; `git:` has the only written wire
    schema (`_git_worker.py` docstring, 22 tests); `ray:` is pickle batching. `ATTRIBUTE_WRITE_COMMANDS` is commented
    out while `ParallelProcess` still sends `set_config` (latent bug, footnote only).
13. Scheduler is a synchronous **min-step front loop** (`composite.py:2599-2700`): eager invoke of due processes,
    advance by the minimum step, reconcile all due updates into **one** update, apply once, then trigger steps.
    Observable behaviour matches the grant's "multi-timestepping"; the mechanism is not an event queue and concurrent
    updates are merged by `reconcile`, not applied in order. Serial/parallel bit-exactness pinned by `tests.py:2317`.
14. Steps fire by data dependency; cycles broken by `priority`; `triggers()`, `perform_update()`, `scatter_port`,
    `_cache` are step-contract extras. Emitters fire because `global_time` is appended to `update_paths` each tick.
15. **Dynamic restructuring is implemented and tested** (`test_dynamic_structure` `tests.py:1533`,
    `test_grow_divide:540`) via `_add`/`_remove`/`_divide`; `_react`/`_move` do not exist at the apply layer
    (reaction rules live in `assembly.fire_rule` inside `BigraphicalReactiveSystem`). Conflicting `initial_state()`
    across edges raises (`composite.py:1394-1415`).
16. Nesting: `interface` + `bridge` wires; nested `update` returns a **list** of bridge updates; `bridge.conduits` is
    read by the engine but undeclared, untested, undocumented.
17. Templates = documents containing `{"_type":"site","_sort":…}`; `fill_sites` by path; `_require_ground_document`
    (`composite.py:2752`). `CompositeSpec` (`composite_spec.py`, with an `emitters:` list, 93 YAML composites in the
    wild) is a *separate authoring descriptor*; lowering its `${name}` onto sites was tried and abandoned.

**Nine cross-report tensions the document must state carefully** (each becomes one sentence in §2 or a footnote):
`python:` exists only in pbest pre-processing · "discrete event scheduler" vs min-step loop · "typed deltas" vs
per-type `apply` · `_react` proposal vs absent · `local:` resolution lives in bigraph-schema (`protocols.py:46`,
`realize.py:288`), not process-bigraph · unit mismatch is silent · emitters are `step` nodes, `CompositeSpec.emitters`
is authoring-only · `interval: null` on steps is inert, `update_condition` is not a core hook · document-embedded
state and edge `initial_state()` are combined and must agree.

## Deliverable

Two tracked Markdown files in `docs/cip/` (the `docs/grant/**` ignore rule does not cover it; `mkdocs build -s`
tolerates pages outside `nav`):

### `docs/cip/CIP-design-review.md` (target 5,000–7,000 words)

0. **How to read this.** Draft for design review, not normative. Position against the arXiv supplement and the
   design-doc list above. Three-column discipline: *Proposed* / *Built* / *Decide*. Corrected grant clock (Y3 now).
1. **What the grant proposed.** Verbatim quotes, no interpretation: 1.1 the three methods; 1.2 Figure 2 (process
   interface: `process_location`, `update_method` KiSAO, `interface` ports→types); 1.3 Figure 3 (composite exchange
   format: `processes`, `wires`, adapters as processes); 1.4 the Aim 3 requirements binding the protocol (static
   checker, annotation-based composition, adapter registry, Docker API exposing the Process Interface, RPC);
   1.5 the grant's pitfalls paragraph.
2. **What exists today.** Compact, every claim cited `repo/path.py:NNN` at the recorded SHAs; each subsection ends
   with "normative example: `tests.py::…`". 2.1 type system and schema language; 2.2 process and step contract
   (`config_schema`, `initialize`, `inputs`/`outputs`, `update`, `initial_state` conflict rule, step extras);
   2.3 composite document (top-level keys, node kinds, `address`, `config`, wires and path language incl. `..`, `*`,
   integer indices, sub-port scatter; state-as-document; emitter node; `interface`/`bridge`); 2.4 orchestration
   (min-step loop, `calculate_timestep`, reconcile-then-apply, step DAG, structural sentinels); 2.5 addresses and
   the five transports (with the `Open` command vocabulary and the `git:` wire schema quoted); 2.6 results and
   handles; 2.7 contracts, units, translators, portability lints; 2.8 serialization, versioning, artifact ids.
3. **Grant ↔ code mapping.** The reviewer's 27-row glossary as a table (term · code identifier · defining file),
   marking rows where the code term is *absent* (`update_method`, adapter registry, XML).
4. **Decisions.** Fixed block shape: *Grant said* (quote) / *Code does* (cited) / *Why they differ* (only what the
   record shows) / *Options* (2–4, each ≤40 words with "costs: who pays") / *Your call:* (blank). No
   recommendations. Final list:
   - **D-A** Declared vs wired ports (synthetic `_layer_*`, inout by double listing, sub-port scatter).
   - **D-B** Update-return semantics: does the protocol name an update kind, or leave it to port types?
   - **D-C** Scheduling contract: `interval`/`calculate_timestep` vs `update_condition`+`next_update_time`.
     (Restructuring is *settled*: stated in §2.4 with one line that the `_react` proposal is unimplemented.)
   - **D-D** Units on ports (kept open by user).
   - **D-E** Semantic annotations on ports and processes; `ProcessContract` as the hook (kept open by user).
   - **D-F** Adapters and the static checker as protocol concepts: `Translator`, `conforms`, lints, LSP are four
     partial checkers (kept open by user).
   - **D-G** Model-artifact carriage (three conventions; pbest's file-existence heuristic).
   - **D-H** Address grammar and resolution (which protocols are standard; registry-dependent vs portable; pbest's
     `python:` notation).
   - **D-I** Remote process interface: is `Open.METHOD_COMMANDS` + `end` the canonical vocabulary every transport
     must carry, given only `git:` has a written schema? Footnote the `set_config` bug.
   - **D-J** Document envelope, JSON Schema, version stamp, `bridge.conduits`, the numpy private state encoding;
     plus results emission (emitter vs listener steps vs external) as a short second half.
   - **D-K** Replay / non-reactive processes: name, constrain, or forbid.
   - **D-L** Exchange format: raw `{schema,state,interface,bridge}` document vs `CompositeSpec` (Figure 3 is closer
     to the latter).
   - **D-M** Nesting and the bridge as part of the standard.
   - **D-N** Ownership and home; relation to the arXiv supplement; COMBINE path. Last.
   Set-aside list (one line each): KiSAO id on the interface; XML serialization.
   The reviewer's drafted Options for D-A, D-B, D-D, D-G, D-I, D-L are used as written; the rest are drafted to
   the same shape.
5. **Appendix A: normative examples.** ~20 tests by name across both repos (from the two library reports).
6. **Appendix B: sources and anchors.** Grant files; design docs; paper; `bigraph-schema` @ `8268aa1` (v1.6.0),
   `process-bigraph` @ `78d1488` (v1.8.4); verified anchors: `composite.py` `Open:401`, `Step:570`, `Process:777`,
   `Composite:1252`, `run:2599`, `_run_inner:2631`, `apply_updates:3128`, `finalize:3064`,
   `_require_ground_document:2752`, `build_step_network:2320`, `trigger_steps:2481`; `edge.py` `inputs:113`,
   `outputs:122`, `interface:144`, `initial_state:104`; `contract.py` `Amendment:52`, `ProcessContract:89`,
   `amend:207`; `core.py` `_compute_unit_scale:1214`, fallbacks 1228-1232, 1278; `schema.py`
   `normalize_address:15`, `Path:279`, `Wires:283`, `Link:300`, `Site:630`; `protocols.py` `local_lookup:46`,
   `unresolvable_addresses:120`, `assert_portable_addresses:142`; `artifacts.py` `_address:106`.
   Sample document: one node from `sms-ecoli/models/partitioned.pbg` (15 MB; quote one node only).

### `docs/cip/GLOSSARY.md`
The same 27-row table as §3, standalone, for use outside the review.

## Standing directives from the user (2026-09-09)

- **v2ecoli is out of scope for deep analysis.** It is unusually large and under very active development. The
  document may cite the three conventions already observed there (`ProcessContract`, unit-typed ports such as
  `float[s]`, synthetic `_layer_*` ordering ports) as *examples of ecosystem practice*, but must not analyze its
  internals further, must not present it as representative, and must say explicitly that it was not examined in
  depth. Execution step 1 below is therefore dropped; D-C is worded as "one large project gates steps with a
  project-level hook that the core does not define" without naming the hook's mapping.
- **No changes of any kind to repositories in the `vivarium-collective` GitHub organization without asking
  first, including opening issues.** Collaborators on another grant use those repos and would read any new issue
  as the user's contribution to their project. Short-term (next few weeks). Everything in this plan lives in
  `compose-api`; nothing is pushed, filed, or commented anywhere else.
- **Tentative approval granted** for the plan as written, with the above amendments. The plan document itself is
  to be saved into the repo as a separate file so the review record survives outside the session.

## Execution steps (after approval)

0. Correct the grant clock in `docs/grant/trd3/tracking/TRACKER.md:8-9` to the 03/01/2024–02/28/2029 windows
   (same branch, same PR). Save this plan verbatim as `docs/cip/PLAN.md` (same PR) so the review record is kept.
1. (Dropped per directive: no further reading of v2ecoli.)
2. Spot-read, at the recorded SHAs, only the passages the document quotes: `Open.METHOD_COMMANDS` block,
   `_run_inner` head, `apply_updates` two-phase comment, `_git_worker.py` docstring, `realize_link` key handling,
   the `core.py` unit-scale fallback, one process node from `partitioned.pbg`, `tests.py:85 test_composite`.
3. Write `docs/cip/CIP-design-review.md`, then `docs/cip/GLOSSARY.md`.
4. Citation check (read-only script in the scratchpad): every `path:NNN` in the document exists and the named
   symbol is on or within 3 lines of that number; every grant quote is a verbatim substring of
   `docs/grant/trd3/TR&D3 - Research Strategy.md`.
5. `make check` (pre-commit hooks cover the new Markdown); `uv run mkdocs build -s` still passes; commit on branch
   `docs/cip-design-review`; open a PR; nothing merged without the user's say-so.

## Verification

- The citation script reports zero unresolved anchors and zero non-verbatim grant quotes.
- Every decision block has all five fields and the *Your call* line is blank; grep confirms no "recommend" in §4.
- No section restates a cite-don't-restate document beyond one sentence plus a link.
- The tracker's grant clock reads Mar–Feb windows and the roll-up is otherwise untouched.
- `make check` and `mkdocs build -s` clean; PR opened.
