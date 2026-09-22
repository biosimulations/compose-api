# Strategy

**Status:** draft, opened 2026-09-13, revised 2026-09-22 (decision 5 added). This is how we reach the goals in [goals.md](goals.md): the layering, the
decisions taken, the order they land in, and the risks. It changes as decisions land. Each decision cites the
analysis it rests on rather than repeating it, so this document stays short and the evidence stays where it was
measured.

---

## 1. The layering

Four layers. Each owns something, and each must not know about the layer above it.

| Layer | What lives here | Owns | Must not know about |
|---|---|---|---|
| **Foundation** | `bigraph-schema`, `process-bigraph` | the type system, the composite document, the scheduler | any toolkit, service or client |
| **Toolkit** | `pbest` — local-or-remote execution, container definitions | running one composite anywhere; producing a recipe from a dependency set | how the service is deployed |
| **Service** | `compose-api` | HPC submission, job state, the simulator registry, results | which client is calling |
| **Clients** | the generated client, the workbench, the web front end | presenting the service to a user | each other |

The foundation is healthy and shared: 84 and 102 releases respectively, and the whole workbench ecosystem depends on
it directly. Everything else in this document is about the middle two layers, where the problems are.

The one structural cycle worth stating plainly: the toolkit's remote path calls the service through the generated
client, and the service imports data types from the toolkit. That is tolerable only because the client is a
generated artifact rather than source. It is one of the reasons for decision 1.

After decision 1 the toolkit, the service and the generated client live in one repository as separate packages of
one workspace. The layering rules above still hold between those packages; sharing a repository is a release
convenience, not permission for the service to import the CLI or the toolkit to import the service.

---

## 2. Decision 1 — consolidate the toolchain into this repository

**Decided 2026-09-13.** Absorb `pbest` as a subpackage of this repository; archive `bsander`, `bsew` and, last,
`pbest`, with explanatory notes and their history intact. Full analysis in [ecosystem-repos.md](ecosystem-repos.md)
and the planning record from that session.

### What the three libraries were

Three serious attempts at the same hard problem: how a composite gets described, containerised and executed, on a
laptop or on HPC. Each advanced the understanding, and each is the foundation the next one stood on. What remains is
the work of taking one of them to production, which is what this decision is for.

- **`bsander` and `bsew`** (Logan Drescher, August–December 2025) were the first working split of the problem into
  two halves: derive a container recipe from a document, and run the document inside the resulting container. The
  split is still the right one. Both were superseded by pbest in February 2026; two of the thirty-seven registered
  simulator definitions still come from this generation.
- **`pbest`** (Ezequiel Valencia, with Lucian Smith, Ryan Spangler, Logan Drescher and Jim Schaff; November 2025 to
  August 2026, 283 commits) rebuilt the pipeline more completely and added the idea the earlier pair lacked: one
  toolkit that runs a composite locally in-process *or* submits it to this service, with the container entrypoint
  re-entering the same local code path. Laptop and cluster genuinely share one implementation. That duality is the
  most valuable idea in any of the three and is the thing consolidation must preserve.

### Why one path, and why now

Three facts, all measured on 2026-09-12 and 13.

**The service uses 17% of the toolkit.** Five symbols from two modules, 188 of 1,096 lines, and the set is closed.
Three small data types and one definition generator. The other 83% is the local-or-remote command line, which the
service never calls — and which, per [goals.md](goals.md) §1, *is the product* a collaborating project installs.
So the consolidation is a decision to own and ship that product, not a decision the service's needs required.

**The boundary produced the drift it was meant to prevent.** This service executes composites with
`process-bigraph 1.0.5`, released 2025-12-27, while the ecosystem runs 1.8.4: thirty-seven releases and 251 days
behind. The cause is mechanical. This repository pins `pbest==0.6.3` exactly; pbest pins `process-bigraph==1.0.5`
and `bigraph-schema==1.0.14` exactly; so the pin on the toolkit freezes the engine beneath it. Goal G8 cannot be met
while that chain exists.

**The separate-product case has not yet arrived.** The workbench ecosystem depends on the foundation directly and on
pbest not at all. pbest's one external consumer takes it as an optional extra behind a lazy import, with a comment
that its API "has historically moved around". The cost of the boundary is paid today; the benefit is still
prospective.

### Attribution, which is easy to get wrong

Four mechanisms, in descending order of how much they preserve.

1. **Merge with history, never by copying.** `git subtree add --prefix=pbest <remote> 0.6.3`, so the original 283
   commits and their authors enter this repository's history. `git blame` then names the people who wrote each line,
   permanently, without anyone having to remember.
2. **The citation record already covers this.** `CITATION.cff` and `.zenodo.json` here already list Valencia,
   Schaff, Drescher and Moraru. Absorbing their work is consistent with credit this repository already gives. Add
   Smith and Spangler for the pbest contributions.
3. **Archive rather than delete.** Read-only, but commits, authorship, blame and issues all survive.
4. **A short `docs/lineage.md`** stating what came from where and who wrote it, for a reader who never sees git.

Archive notes should point all three repositories **directly here**, not through each other. Archive `pbest` last
and only after a release has shipped from its new home; it is on PyPI and pinned by a real consumer. Keep the package
name `pbest`.

### The phases

| Phase | What | Gate |
|---|---|---|
| 1 | Harvest two ideas from bsander into the CIP review (decision D-H, the in-document address protocol) and tracker row `A3.4.docker` (the multi-environment premise); record deviations; draft archive notes. The owner archives. | Deviations recorded for `A2.2`, `A3.3a`, `A3.4.docker`, D3. |
| 2 | Bring pbest in unchanged from **tag 0.6.3** (its published tags are not on its `main`), hold the engine at 1.0.5, add the console script, keep the import direction as today. | `pbest containerize` output byte-identical to today; simulator hash unchanged; original authors visible in `git log`. |
| 2a | **Put the local execution path under test first.** pbest has eleven tests across nine files, four of them empty, and the code most likely to break under an engine upgrade is the code the service never runs. | End-to-end tests through `run_experiment` on existing `.pbg` fixtures, in the fast CI job. |
| 2b | Bring `compose-api-client` in the same way, with its history, as a third workspace package; keep its hand-written `utils/run_simulation_and_wait.py`, which the generator does not produce, outside the generated tree so regeneration cannot clobber it. | `make clients` writes only in-repo; the regenerated client is byte-identical to the published 0.2.0 apart from the hand-written file. |
| 3 | Decide the identity consequence **before** the engine upgrade lands: see decision 2. | A dated choice between a scheduled rebuild wave and digest identity first. |
| 4 | Upgrade the engine, alone, in its own pull request. | Phase 2a tests green; phase 3 decided; one composite end to end on the containerised SLURM backend. |
| 5 | Publish `pbest`, `compose-api-client` and the service from the new home, then archive the old repositories. | One release of all three from here before any archive. |

### Packaging after the merge

One repository, one `uv` workspace, three distributions:

| Distribution | What it is | Must stay free of |
|---|---|---|
| `pbest` | the toolkit and its command line, the product a collaborator installs | FastAPI, asyncpg, asyncssh, SQLAlchemy — a laptop install must not pull the server |
| `compose-api-client` | the generated client, plus its one hand-written helper | anything but its HTTP stack |
| `compose-api` | the service | — it depends on the other two, pinned to the same workspace version |

The package names on PyPI do not change, so no downstream import breaks. The payoff is the one that motivated the
open follow-up on 404s: a request or response model change becomes one pull request and one release, instead of the
four-step release across three repositories that `CLAUDE.md` describes today.

---

## 3. Decision 2 — identity is an image digest

**Decided in principle; sequencing set here.** The full case is
[plan-container-runtimes.md §1](plan-container-runtimes.md). In one paragraph: today the identity of a simulator is
the md5 of a generated recipe, and that recipe is not deterministic — it runs an unpinned system upgrade, fetches a
tool from a `latest` URL, resolves dependencies at build time, and sits on a mutable base tag. Two builds of the
byte-identical recipe months apart produce different images under the same identity. A digest describes what was
actually built; a recipe hash describes only what was asked for. Goal G3 is unreachable until this changes.

**Why it is sequenced before breadth.** Every simulator added under a non-reproducible identity multiplies the
problem. *Registering* for G4 waits for this; *developing and validating* new simulators does not, and runs as a
parallel track (§7).

**It does not wait on the runtime choice.** Singularity/Apptainer can already pull an OCI image by digest
(`docker://…@sha256:…`), so digest identity can land on today's runtime. Decision 3's runtime question, which
depends on the cluster administrators, is independent of it.

**Why it interacts with decision 1.** Absorbing pbest changes what the `pbest_tag` baked into the recipe means, and
upgrading the engine changes the recipe text. Either one invalidates every existing simulator identity and rebuilds
every container. Landing digest identity first makes both non-events; landing it afterwards means paying for one
rebuild wave and then changing the identity scheme anyway. Decision 1 phase 3 exists to force that choice.

---

## 4. Decision 3 — registered simulators only, on the trusted tier

**Decided 2026-09-13.** In this funding year composites may only wire together processes from the curated registry.
This is an access-control boundary, not an isolation boundary, and [goals.md](goals.md) G6 says so.

What it means for the runtime: the trusted tier in [plan-container-runtimes.md §3.1](plan-container-runtimes.md) is
sufficient. Provisionally Enroot with the Pyxis scheduler plugin, contingent on what the cluster administrators will
install. The untrusted tier — a KVM-backed microVM, or gVisor given that no workload needs a GPU — is parked with a
trigger: **the day a composite can carry a process a collaborator wrote rather than one we registered.** When that
day comes, §4.2 of that document is the starting point and the sandbox moves into scope.

---

## 5. Decision 4 — converge the two hosted backends

**Decided as a goal 2026-09-13; the path is proposed, not fixed.** Two hosted composition backends exist: this one at
`compose.cam.uchc.edu` and `viva-api` at `sms.cam.uchc.edu`. Deviation D2 already records this. Two backends for one
standard is itself a maturity problem, and goal G7 names convergence.

**What is known.** `viva-api` lives in `vivarium-collective`, declares none of this repository's packages, and serves
a different program. Nothing else about it has been examined; the standing directive is that repositories in that
organisation are read-only for this work.

**First steps, in order.**

1. **Survey `viva-api` read-only**, the way `viva-superpowers` was surveyed in
   [plan-testing.md §1.7](plan-testing.md): what it runs, how it tests, what engine version it pins, how it identifies
   a simulator.
2. **Name the convergence points that cost least.** Almost certainly: the engine version (both should track
   the same `process-bigraph` minor), the process registry (one registry, two consumers), the identity scheme
   (decision 2 applied to both), and the **environment resolver**. `viva-api`'s own plan (its decision D10) already
   chose per-composite environments selected or built from a spec and keyed by spec hash and image digest, and says
   outright that one environment for everything does not scale. Decision 5 reaches the same shape independently,
   which makes the resolver the most natural first thing to share. None of these requires merging code.
3. **Propose the Year 4 target**: one front door per program if that is what the programs need, over one execution
   backend. Whether that backend is this service, `viva-api`, or a third thing is the decision the survey informs.

No timeline is claimed beyond that, and no change to `viva-api` is proposed here.

---

## 6. Decision 5 — bring the simulator wrappers in as tiered registry entries

**Decided 2026-09-22.** The `viva-*` simulator wrappers in `vivarium-collective` enter this service's registry as
pinned, built and tested *entries*, each at a stated curation level. They are not merged into this repository and
not forked. Composites of several of them get an environment built for that composite.

### What exists, measured 2026-09-22

- **This registry is one image, not a catalog.** The thirty-seven "registered simulators" are thirty-seven versions
  of one ~1.3 GB image, built from a hard-coded list of four libraries fetched from `biosimulations/registry`. The
  submitted document is never read to decide what goes in it. A registry row has no name, no status and no tests;
  the allow-list is passed in and never enforced; no port types are stored anywhere.
- **`viva-catalog` is a discovery list, not a registry.** It is regenerated daily from every repository carrying a
  topic, and records name, source and `ref: main`. It has no version, environment, dependency list, status or adapter
  category. That is the right job for it, and this decision does not ask it to do more.
- **The wrappers cannot share one environment.** None is on PyPI and most have no CI. Their `process-bigraph` floors
  run from `>=0.0.10` to `>=1.8.3` with no ceilings. Several need what pip cannot supply: conda (CompuCell3D, Smoldyn
  on Linux), a C++ build (Mem3DG), Node (Artistoo), Rust (the CPM engine), Docker (Chaste). Process names share one
  flat namespace, so two wrappers can register the same name.
- **The material for a curation standard already exists.** `study.yaml` (claim, expected behaviour, findings,
  readouts), which the catalog already harvests; the executable / calibrated / validated matrix one composite keeps
  in its README; and test-audit and benchmark tooling in `viva-superpowers`.

### The curation ladder

Every entry carries one level. Each rung has a gate a machine can check, except the last, which also needs a person.

| Level | Gate | Where it can run |
|---|---|---|
| 1. **listed** | discovered from the catalog; pinned to a commit | locally, through the toolkit |
| 2. **installable** | its environment spec builds; the result has a digest | locally |
| 3. **tested** | the wrapper's own test suite passes inside that environment, in our CI | locally and on HPC |
| 4. **validated** | at least one `study.yaml` whose findings confirm against a published reference or an independent simulator | locally and on HPC |
| 5. **curated** | all of the above, plus documentation and declared port types and units, plus sign-off by a named reviewer recorded in the manifest | locally and on HPC |

Levels only go up by passing a gate and go down when a gate stops passing: a new pinned commit starts again at
*listed* until CI re-establishes its level. Every result records the level of each component it used, so a reader
of a result knows how much to trust each part of it.

**Bring everything in, then raise it.** Every wrapper in the catalog enters at *listed* on day one. That makes the
registry's breadth honest immediately and turns curation into visible, systematic work on a queue, rather than a
gate nothing passes. It also changes what goal G6 means by "registered": an entry at *tested* or above.

### Where the curation record lives

A versioned manifest in this repository, reviewed by pull request and loaded into the database. It holds, per entry:
source, pinned commit, environment spec, level, the evidence for that level, port types when declared, and the
reviewer. The catalog is read daily, read-only, to discover new wrappers and new commits; nothing is written back to
`vivarium-collective`. The manifest's exact schema is its own design document.

### Environments for a composite of N components

One environment for every simulator does not scale, as the dependency survey shows and as `viva-api` concluded
independently. In order of preference:

1. **Resolve one environment per composite** from the pinned specs of its components, build it, and identify it by
   digest (decision 2). A second composite with the same components reuses it.
2. **Pre-build the combinations people actually use** (for example ODE and SSA together, or a spatial simulator with
   its usual partners) as cached bundles. A bundle is an optimisation of rule 1, not a separate mechanism.
3. **Split across containers when components cannot share one environment**, because the resolver finds a conflict
   or a component needs a runtime pip cannot provide. The processes then talk through the process protocol, one
   container each. This is exactly grant row `A3.4.docker`, which the tracker records as not yet done.

Namespacing process addresses by entry removes the flat-name collision as a side effect.

### Adapters

Adapters are a category of the same registry, on the same ladder. They cannot reach *curated* without declared port
types and units, which is also what lets a checker suggest them later. Seed the category from code that already
exists: `viva-basic-processes`' expression step and `spatio-flux`'s count/concentration conversion (goal G5).

### The phases

| Phase | What | Gate |
|---|---|---|
| A | Manifest schema; ingest the catalog; every wrapper appears at *listed*. Enforce the allow-list the service already receives. | Service rejects unlisted addresses (G6); registry lists every catalog wrapper. |
| B | CI that builds each entry's environment and runs its tests; levels 2 and 3 computed, not asserted. | A nightly report of every entry's level, and why. |
| C | The per-composite resolver, after digest identity (decision 2). | Two wrappers from different entries run in one composite on HPC. |
| D | Container splitting for conflicting components. | One composite with processes in two containers (`A3.4.docker`). |
| E | Validation and curation: the spatial and particle simulators for G4, the two adapters for G5, first. | Named entries at *validated* and *curated*, each with its evidence linked. |

Phases A and B do not depend on decisions 1 or 2 and can start now. C waits for digest identity. E's validation work
happens in the wrapper repositories and can run in parallel from the start.

---

## 7. Sequencing and risks

**The four qualities, in the order they land.** Each earlier one is a precondition for the next.

1. **Hosted reliability** (G2). Underway: correct error semantics, the job-monitor fix, and the SLURM and container
   build paths now run in CI on every pull request without a cluster.
2. **Installability** (G1). Blocked by the engine lag, which decision 1 removes, and until this month by a personal
   registry account in the production path, now a setting.
3. **Reproducibility** (G3). Decision 2. Must precede breadth.
4. **Breadth** (G4, G5). Year 2's promise. Last *on the service*, because each registration inherits whatever
   identity and registry model exists when it lands.

**A parallel breadth track.** Year 3 ends on 2027-02-28, and the report must show progress on Year 2's breadth
commitments. So new simulators and adapters are developed and validated in their wrapper repositories now, and
decision 5's phases A and B run now; only *registering them to run on HPC* waits for reproducibility. If digest
identity slips past the end of Year 3, the registration step becomes a dated deviation, not a silent miss.

**Reliability work this implies.** Goal G6's test, rejecting what is not registered, needs code that does not run
today: the allow-list reaches the handler and is ignored. It belongs with the reliability work, as decision 5
phase A.

**Risks, named.**

- **The engine upgrade will break code we do not exercise.** Thirty-seven releases, landing almost entirely in the
  83% of pbest the service never runs, which has eleven tests. Phase 2a is the mitigation and is not optional.
- **The identity change causes a rebuild wave.** Every existing simulator identity is a recipe hash; changing the
  recipe or the scheme invalidates all thirty-seven. Decision 2 must be made before the engine upgrade (decision 1
  phase 4), not discovered after.
- **The published toolkit tags are not on its main branch.** Merging from `main` would silently revert a released
  feature. Merge from the tag, and reconcile the source repository first.
- **The reporting metric moves the wrong way.** Prior reports count repositories; this work archives three. The
  report should count tools maintained and say why. [goals.md §4](goals.md) has the framing.
- **The cluster administrators may decline the runtime we prefer.** Decision 3's runtime choice is contingent on
  them; [plan-container-runtimes.md §5](plan-container-runtimes.md) lists what to ask and what each answer costs.
- **Old wrappers will break on the current engine.** Most declare `process-bigraph>=0.0.10` and were never run
  against 1.x. Decision 5's phase B will say which, and many will sit at *installable* until someone fixes them.
- **Environment conflicts are found late.** A composite whose components cannot share an environment fails at
  resolve time, on the service, unless the resolver runs in the toolkit too and reports the conflict before
  submission. The resolver should live in the toolkit for that reason.
- **Curation is labour.** Five rungs across ~50 wrappers is more work than the team can do at once. Level 1 for
  everything and levels 3–5 for the Year 3 targets first; the rest rise as people use them.

---

## 8. What this document does not decide

- **The repository's name.** Once it holds the service, the toolkit, the local runner and the client, `compose-api`
  names one of four things. A broader name is reasonable. A rename touches the container image, the published client
  name, the production host, the citation file and the Zenodo concept DOI, so it is a separate, deliberate change.
- **The untrusted runtime.** Parked with its trigger in decision 3.
- **The manifest schema.** Decision 5 says what the curation record holds; the exact schema is its own document.
- **Which wrappers reach *curated* first**, beyond the Year 3 targets named in the tracker.
- **Which backend survives convergence.** Decision 4 sets the goal and the first steps, not the answer.

## Sources

- [goals.md](goals.md) — what this strategy serves.
- [ecosystem-repos.md](ecosystem-repos.md) — the three libraries, the wrapper repositories, the consolidation
  question as first framed.
- The 2026-09-22 read-only survey of `viva-catalog`, a sample of eleven wrappers, and `viva-api`'s plan, summarised in
  decision 5.
- [plan-container-runtimes.md](plan-container-runtimes.md) — the identity invariant, the workload profile, the
  runtime options and the trust model.
- [plan-testing.md](plan-testing.md) — the testing findings and what has landed.
- [cip/CIP-design-review.md](cip/CIP-design-review.md) — the protocol and its open decisions.
- [grant/trd3/tracking/TRACKER.md](grant/trd3/tracking/TRACKER.md) and
  [DEVIATIONS.md](grant/trd3/tracking/DEVIATIONS.md) — what was promised and where we diverged.
- The Year 1 and Year 2 progress reports and the External Advisory Board report, in `docs/grant/`.
