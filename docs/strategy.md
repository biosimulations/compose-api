# Strategy

**Status:** draft, opened 2026-09-13. This is how we reach the goals in [goals.md](goals.md): the layering, the
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

---

## 2. Decision 1 — consolidate the toolchain into this repository

**Decided 2026-09-13.** Absorb `pbest` as a subpackage of this repository; archive `bsander`, `bsew` and, last,
`pbest`, with explanatory notes and their history intact. Full analysis in [ecosystem-repos.md](ecosystem-repos.md)
and the planning record from that session.

### What the three libraries were

Three serious attempts at the same hard problem: how a composite gets described, containerised and executed, on a
laptop or on HPC. Each advanced the understanding. None reached production quality, which is a matter of time and
staffing rather than of the thinking behind them.

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
| 3 | Upgrade the engine, alone, in its own pull request. | Phase 2a tests green; one composite end to end on the containerised SLURM backend. |
| 4 | Decide the identity consequence **before** phase 3 lands: see decision 2. | A dated choice between a scheduled rebuild wave and digest identity first. |
| 5 | Publish `pbest` from the new home, then archive the old repository. | One release from here before the archive. |

---

## 3. Decision 2 — identity is an image digest

**Decided in principle; sequencing set here.** The full case is
[plan-container-runtimes.md §1](plan-container-runtimes.md). In one paragraph: today the identity of a simulator is
the md5 of a generated recipe, and that recipe is not deterministic — it runs an unpinned system upgrade, fetches a
tool from a `latest` URL, resolves dependencies at build time, and sits on a mutable base tag. Two builds of the
byte-identical recipe months apart produce different images under the same identity. A digest describes what was
actually built; a recipe hash describes only what was asked for. Goal G3 is unreachable until this changes.

**Why it is sequenced before breadth.** Every simulator added under a non-reproducible identity multiplies the
problem. Goal G4 waits for this.

**Why it interacts with decision 1.** Absorbing pbest changes what the `pbest_tag` baked into the recipe means, and
upgrading the engine changes the recipe text. Either one invalidates every existing simulator identity and rebuilds
every container. Landing digest identity first makes both non-events; landing it afterwards means paying for one
rebuild wave and then changing the identity scheme anyway. Phase 4 above exists to force that choice.

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
2. **Name the three convergence points that cost least.** Almost certainly: the engine version (both should track
   the same `process-bigraph` minor), the process registry (one registry, two consumers), and the identity scheme
   (decision 2 applied to both). None of these requires merging code.
3. **Propose the Year 4 target**: one front door per program if that is what the programs need, over one execution
   backend. Whether that backend is this service, `viva-api`, or a third thing is the decision the survey informs.

No timeline is claimed beyond that, and no change to `viva-api` is proposed here.

---

## 6. Sequencing and risks

**The four qualities, in the order they land.** Each earlier one is a precondition for the next.

1. **Hosted reliability** (G2). Underway: correct error semantics, the job-monitor fix, and the SLURM and container
   build paths now run in CI on every pull request without a cluster.
2. **Installability** (G1). Blocked by the engine lag, which decision 1 removes, and until this month by a personal
   registry account in the production path, now a setting.
3. **Reproducibility** (G3). Decision 2. Must precede breadth.
4. **Breadth** (G4, G5). Year 2's promise. Last, because each addition inherits whatever identity and registry model
   exists when it lands.

**Risks, named.**

- **The engine upgrade will break code we do not exercise.** Thirty-seven releases, landing almost entirely in the
  83% of pbest the service never runs, which has eleven tests. Phase 2a is the mitigation and is not optional.
- **The identity change causes a rebuild wave.** Every existing simulator identity is a recipe hash; changing the
  recipe or the scheme invalidates all thirty-seven. Decision 2 must be made before phase 3, not discovered after.
- **The published toolkit tags are not on its main branch.** Merging from `main` would silently revert a released
  feature. Merge from the tag, and reconcile the source repository first.
- **The reporting metric moves the wrong way.** Prior reports count repositories; this work archives three. The
  report should count tools maintained and say why. [goals.md §4](goals.md) has the framing.
- **The cluster administrators may decline the runtime we prefer.** Decision 3's runtime choice is contingent on
  them; [plan-container-runtimes.md §5](plan-container-runtimes.md) lists what to ask and what each answer costs.

---

## 7. What this document does not decide

- **The repository's name.** Once it holds the service, the toolkit, the local runner and the client, `compose-api`
  names one of four things. A broader name is reasonable. A rename touches the container image, the published client
  name, the production host, the citation file and the Zenodo concept DOI, so it is a separate, deliberate change.
- **The untrusted runtime.** Parked with its trigger in decision 3.
- **The simulator wrappers.** Out of scope; [ecosystem-repos.md §3](ecosystem-repos.md).
- **Which backend survives convergence.** Decision 4 sets the goal and the first steps, not the answer.

## Sources

- [goals.md](goals.md) — what this strategy serves.
- [ecosystem-repos.md](ecosystem-repos.md) — the three libraries, the wrapper repositories, the consolidation
  question as first framed.
- [plan-container-runtimes.md](plan-container-runtimes.md) — the identity invariant, the workload profile, the
  runtime options and the trust model.
- [plan-testing.md](plan-testing.md) — the testing findings and what has landed.
- [cip/CIP-design-review.md](cip/CIP-design-review.md) — the protocol and its open decisions.
- [grant/trd3/tracking/TRACKER.md](grant/trd3/tracking/TRACKER.md) and
  [DEVIATIONS.md](grant/trd3/tracking/DEVIATIONS.md) — what was promised and where we diverged.
- The Year 1 and Year 2 progress reports and the External Advisory Board report, in `docs/grant/`.
