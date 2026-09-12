# Associated repositories: what exists, and whether we still need it all

**Status:** survey opened 2026-09-12 at the user's request, read-only. Part 1 documents two libraries
(`bsew`, `bsander`) that this repository touches without naming anywhere. Part 2 indexes the simulator wrappers.
Part 3 frames a consolidation question and does **not** answer it. Facts were checked against GitHub and PyPI on
2026-09-12; nothing was changed in any other repository.

---

## 1. `bsew` and `bsander`

Both live in the **`biosimulators`** organisation, not `vivarium-collective`. Both are absent from PyPI: a request
for either package returns 404. Both are referenced from this repository already, neither is documented here, and
neither is pinned.

| | `biosimulators/bsew` | `biosimulators/bsander` |
|---|---|---|
| Described as | "Wrapper package for running Process Bigraph experiments in a docker environment" | "Analyzes a Process-Bigraph `.pbif` file, and creates a configuration that will run in a given environment" |
| Last pushed | 2025-12-04 | 2025-08-28 |
| On PyPI | no (404) | no (404) |
| How it reaches us | cloned inside a **deployed** simulator definition | a `[tool.uv.sources]` git override |

**`bsew` is in a shipped artifact, unpinned.** The simulator definition this repository now builds in CI
(`tests/fixtures/resources/production_simulator.def`, copied verbatim from the live deployment) contains:

```
git clone https://github.com/biosimulators/bsew.git  /runtime
python3 -m pip install -e /runtime
```

No branch, no tag, no commit. The image therefore depends on whatever `main` happens to be at build time. This is
the same class of problem as item 6 in [plan-container-runtimes.md](plan-container-runtimes.md) — the definition
hash identifies a recipe that does not reproduce — but here it is concrete and in production, not hypothetical.

**`bsander` reaches us through a dead override.** `pyproject.toml` redirects it to a git URL, but it appears in no
dependency list and no lock entry, so the override is inert. It is F14 in [plan-testing.md](plan-testing.md), and
removing it is one of the open follow-ups.

**Where they appear in the grant record.** `bsander` is cited under `A2.2` for the `.pbif` format and under `A3.3a`
as one of four partial static checkers. `bsew` is cited under `A3.2.engines` as delegating to
`process_bigraph.Composite` rather than being a second orchestrator, and in `DEVIATIONS.md` as the mechanism by
which containerisation happens per composite rather than per simulator. So both are load-bearing in the grant
narrative while being undocumented and unreleased in practice.

---

## 2. The simulator wrappers

**They are no longer called `pbg-*`.** The organisation completed a `pbg-` → `viva-` rename; `viva-cellpack`'s own
description still records it as "legacy pbg- name; part of the pbg→viva rebrand", and `viva-superpowers` was
`pbg-superpowers` (§1.7 of the testing plan). Counted on 2026-09-12 across 173 repositories in
`vivarium-collective`:

| Prefix | Count |
|---|---|
| `viva-` | 54 |
| `pbg-` | 1 (`pbg-eps-biofilm`) |

Anything still looking for `pbg-xxx` will find almost nothing. Cross-references inside the org have not all caught
up either: `viva-membrane-actin-composite` still describes itself in terms of `pbg-mem3dg` and `pbg-readdy`.

**An index already exists, and it is maintained automatically.** `vivarium-collective/viva-catalog` is the ecosystem
ledger. It discovers every public repository carrying the `viva-marketplace` GitHub topic, regenerates
`modules.json`, and builds an artifact index by shallow-cloning each repository and scanning it for processes,
steps, composites, studies and investigations.

**So this document deliberately does not restate that list.** A second hand-maintained index would be stale within
weeks and would compete with the generated one. What is worth recording is how to read it and where it does not
reach:

- 51 repositories carry the topic; the generated index held 49 entries when checked, so it lags slightly.
- Of 53 non-archived `viva-`/`pbg-` repositories, 7 are absent from the index: `viva-api`, `viva-catalog`,
  `viva-compiler`, `viva-demo`, `viva-superpowers`, `viva-template`, `viva-workspace`. Every one is **tooling**
  rather than simulator content, so the omission looks deliberate rather than accidental. It does mean the index
  answers "what can I compose with", not "what does this ecosystem consist of".

**Treat these as strongly associated with this project.** They are the simulators whose definitions this service
builds and runs. A wrapper's process interface changing is a change to what `compose-api` executes, even though no
dependency here names it.

---

## 3. The question this survey was asked to frame, not answer

*Do we still need this many repositories and libraries?* The user's own hypothesis is that some predate the
requirements being well defined. Nothing below is a recommendation.

**What the evidence supports so far.**

- **The wrappers are not the problem.** Roughly fifty repositories each wrapping one simulator is a defensible
  shape: they have separate upstreams, separate licences, separate release cadences, and a generated index already
  makes them addressable. Consolidating them would trade a long list for a monorepo with fifty upstream pins.
- **The tooling layer is where the duplication looks real.** Counting only what this project has already surveyed:
  `pbest`, `bsew` and `viva-compiler` all delegate to `process_bigraph.Composite`; `bsander`, `bigraph-schema`
  validation, `process-bigraph-lang`'s language server and `viva-template`'s workspace lint are four partial static
  checkers (`A3.3a` says so in the tracker); and `pbest containerize`, `bsew` and this service are three ways to get
  a composite into a container.
- **Two of them are unreleased and idle.** `bsew` and `bsander` have no PyPI presence and have not been pushed in
  nine and twelve months, yet one of them is installed, unpinned, into a deployed image.

**Questions worth deciding before consolidating anything.**

1. Is `bsew` still the containerisation path, or has `pbest containerize` plus this service replaced it? If
   replaced, the deployed simulator definitions still clone it and would need regenerating.
2. Is `bsander` still the `.pbif` analyser the grant cites, or is that role now `viva-compiler`'s? `A3.3a` is
   already marked as having no single checker.
3. Should either be published to PyPI, or archived? The current state, unreleased but installed from `main`, is the
   worst of both.
4. Does the ecosystem index need to cover tooling as well as content, or is "what can I compose with" the right
   scope for it?
