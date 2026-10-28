# Internal documentation

**Internal planning, not user documentation.** Everything listed here is planning, analysis and grant material for
the team. This repository is public, so these files are readable by anyone browsing it on GitHub; they are written
with that in mind. They are kept off the published documentation site by `exclude_docs` in `mkdocs.yml`, because
they are not user documentation. The site carries `index.md`, `authentication.md`, `webapp.md`, `cli.md`, and the
generated module reference. If you add a planning document here, add it to that list.

## Where to start

Several documents answer different questions. Start with the one that matches yours.

| If you want to know… | Read | Kind | Last measured |
|---|---|---|---|
| who this is for, what it must do, and what "done" means | [goals.md](goals.md) | direction, changes rarely | 2026-10-13 |
| how we get there: layering, decisions (toolchain, identity, trust, convergence, simulator wrappers), order, risks | [strategy.md](strategy.md) | direction, changes as decisions land | 2026-10-13 |
| what the grant promised and where we diverged, row by row | [grant tracker](grant/trd3/tracking/TRACKER.md), [deviations](grant/trd3/tracking/DEVIATIONS.md) | record | 2026-10-06 |
| what the Year 2 progress report says about TR&D3, against our goals | [RPPR-C2Y2-review.md](grant/trd3/tracking/RPPR-C2Y2-review.md) | analysis | 2026-10-07 |
| TR&D3's Year 3 progress, outlined for the progress report, with evidence and a plan to March 2027 | [trd3-y3-progress-outline.md](trd3-y3-progress-outline.md) | report outline, items to fill | 2026-10-13 |
| a 20-minute talk on Year 3 for the External Advisory Board, slide by slide | [trd3-y3-deck-storyboard.md](trd3-y3-deck-storyboard.md) | storyboard | 2026-10-13 |
| what the composition protocol is and its open design decisions | [CIP design review](cip/CIP-design-review.md), [glossary](cip/GLOSSARY.md), [its plan](cip/PLAN.md) | analysis | 2026-09-09 |
| which libraries and repositories surround this one, and whether we need them all | [ecosystem-repos.md](ecosystem-repos.md) | analysis | 2026-10-06 |
| why container identity should be a digest, and which runtime to run on | [plan-container-runtimes.md](plan-container-runtimes.md) | analysis | 2026-10-13 |
| how testing works, what was broken, what was fixed | [plan-testing.md](plan-testing.md) | analysis, partly implemented | 2026-10-13 |
| the `compose-api` command line and the generated client it is built on | [plan-cli.md](plan-cli.md) | plan, implemented | 2026-10-13 |
| run traces from process-bigraph events, datasets a run advertises, and the permission seam for auth | [plan-observability.md](plan-observability.md) | plan, implemented except step 5 (owner at submit) | 2026-10-13 |
| interface manifests per environment, and writing composites in the web app | [plan-authoring.md](plan-authoring.md) | plan, implemented (0.7.14) | 2026-10-13 |
| SED-ML models (BioModels, biosimulations.org, uploads) run on several solvers and compared; catalog, environments and solvers defined | [plan-sedml.md](plan-sedml.md) | plan, implemented (curated routes and interpolation deferred) | 2026-10-13 |
| environment builds as jobs of their own, image artifacts recorded, builds on Kubernetes, publishing | [plan-environment-builds.md](plan-environment-builds.md) | plan, phases 1–4 implemented; publishing deferred | 2026-10-13 |
| environment versions as database records: locked with uv, created and chosen through the API, recorded on every run; the registry as the build trust gate | [plan-environment-versions.md](plan-environment-versions.md) | plan; steps 1–5a merged (0.7.41); rest superseded by composition | 2026-10-25 |
| environments composed from curated manifest entries: pixi (uv export), compliance composites per entry, registry_env migrated off pbest, mash-ups on demand | [plan-environment-composition.md](plan-environment-composition.md) | done: 0–8e; 7c live 2026-10-27 (0.7.64) | 2026-10-27 |
| each solver's known problems in a suite: excused per solver, flagged when fixed, curated by an admin in the webapp or CLI | [plan-known-problems.md](plan-known-problems.md) | done: 1, 2a, 3 (0.7.49), 2b (0.7.62) |  2026-10-26 |
| viewers for datasets, registered per type and loaded lazily; the results bundle in 3D | [plan-viewers.md](plan-viewers.md) | plan, implemented (A1–A3 later) | 2026-10-13 |
| signing in to the web UI: a PKCE single-page app (no backend-for-frontend), the Auth0 SPA application, hardening | [plan-webapp-login.md](plan-webapp-login.md) | done: live, CSP enforced, documented | 2026-10-27 |
| the web UI's sign-in switched on, capabilities from `/auth/me`, environment version pages and admin actions, one suite run at a time | [plan-webapp-admin.md](plan-webapp-admin.md) | done (0.7.61); a signed-in check in production left | 2026-10-27 |
| runs recorded as `requested` and dispatched by a worker that survives restarts; caps, priorities, resumable suite runs | [plan-durable-submission.md](plan-durable-submission.md) | plan, implemented (0.7.31) | 2026-10-22 |
| checking SED-ML comparisons against BioSimulators: legacy runs as references, and biosim's `/verify` API as an oracle | [plan-verify-oracle.md](plan-verify-oracle.md) | done: V0–V5 (0.7.66) | 2026-10-28 |
| a signed-in user's own runs (owners stamped at submit), favorites, and studies that group and share runs | [plan-favorites-and-studies.md](plan-favorites-and-studies.md) | active: step 1a in review | 2026-10-28 |
| the web UI at `/ui`: pages, viewers, composite authoring, how it is built | [webapp.md](webapp.md) | user documentation | 2026-10-13 |
| the `compose-api` command line, with its generated reference | [cli.md](cli.md) | user documentation | 2026-10-13 |

## Active plan, and what is parked (2026-10-28)

We work one plan at a time: the active plan runs to its end, and anything found outside it is recorded here and
raised, not fixed on the spot.

**Active: [plan-favorites-and-studies](plan-favorites-and-studies.md)** (2026-10-28): owners stamped at submit and a
"Mine" filter (step 1a, which takes over plan-observability step 5), then favorites, then a plan for studies.

**Done:**
- [plan-verify-oracle](plan-verify-oracle.md): V5, the verdicts on the comparison and suite pages, live in 0.7.66
  (2026-10-28). Its open questions remain: a service account in Auth0, and the volume biosim will accept before
  `verify: failing` runs on a schedule.
- [plan-environment-composition](plan-environment-composition.md): its last step, 7c (viva-pde-particle composed, the
  PDE + particle + ODE mash-up), live in 0.7.64 (2026-10-27).
- Before them: plan-webapp-admin (0.7.61; Jim's signed-in check in production is left) and plan-known-problems 2b
  (0.7.62).
- Outside any plan, the simulation page at Jim's request (0.7.67–0.7.69): Input and Figures tabs, the trace and events
  as one tab, a leaner Overview, dataset rows that open their view, a glyph per dataset, and Table/Plot/Text viewers
  for tables and figures.

**Parked**, with where each stopped:

| Thread | Done | Left |
|---|---|---|
| [plan-vcell-ode](plan-vcell-ode.md) | 1–4 | report VCell bugs: BIOMD 112 (`null`), 175 (unknown identifier), 56 and 168 (disagree), 137 (solve error); 235 (out of memory) and 255 (timeout) |
| [plan-observability](plan-observability.md) | 0–4 | 5: taken over by plan-favorites-and-studies (2026-10-28) |
| [plan-environment-builds](plan-environment-builds.md) | phases 1–4 | publishing |
| Named composed environments | | Only registry_env can be a named composed environment: `versions.py`, `resolver.py` and `lifecycle.py` each take "the" `shared` environment (the default for runs that name none, the resolver's first choice, a mash-up's Python), and the kinds are `shared`, `prebuilt` and `mash-up`. A curated repo (a viva-* entry) runs in registry_env, in a mash-up, or as a prebuilt image. A short plan: a `composed` kind requiring `entries`, `shared` kept as the default, and the resolver ranking named composed environments ahead of mash-ups; composition 7c would use it. Found 2026-10-27 |
| Emitters in submitted documents | | Folded into composition 7c-1 (2026-10-27): process-bigraph's `process_bigraph.emitter` becomes an admitted entry, and documents name `local:process_bigraph.emitter.RAMEmitter` |
| viva-pde-particle's next commit | | viva-pde-particle#69 makes `SpatialExport`'s output replace (composition 7c-5). Taking it means a manifest bump of its `commit`, a new prebuilt image registered as viva-pde-particle@3, and `environments create mash-05956395cf` for @3 |
| Test isolation | | `tests/environments/test_contents.py::test_the_reread_job_scripts_leave_what_they_read_beside_the_image` fails when run after `tests/registry tests/api tests/environments` (a settings layer left active: `simulation_store_base_path`); passes alone and in CI's order |
| Test isolation, staging | | two `tests/simulation/test_staging.py` permission tests fail in the full local order and pass alone (found 2026-10-26) |
| Open PRs | | #345 (vivarium-workbench plan), dependency bumps |

**Direction** documents say what we intend. **Analysis** documents measure something and lay out options; they are
dated because measurements go stale. **Record** documents track commitments. When two disagree, the direction
document is the plan of record, and the disagreement should become a dated deviation rather than stay implicit.

The grant text itself (`grant/*.md`, `grant/trd3/*.md`) is git-ignored and exists only on machines where it was
placed by hand; the `tracking/` folder is the versioned part.
