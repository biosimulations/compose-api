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
| environment versions as database records: locked with uv, created and chosen through the API, recorded on every run; the registry as the build trust gate | [plan-environment-versions.md](plan-environment-versions.md) | plan; steps 1–5a merged (0.7.41) | 2026-10-25 |
| viewers for datasets, registered per type and loaded lazily; the results bundle in 3D | [plan-viewers.md](plan-viewers.md) | plan, implemented (A1–A3 later) | 2026-10-13 |
| signing in to the web UI: a PKCE single-page app (no backend-for-frontend), the Auth0 SPA application, hardening | [plan-webapp-login.md](plan-webapp-login.md) | plan; built, switched on by W2 (#359) | 2026-10-25 |
| the web UI's sign-in switched on, capabilities from `/auth/me`, environment version pages and admin actions, one suite run at a time | [plan-webapp-admin.md](plan-webapp-admin.md) | plan, decided; steps 1–2 under way | 2026-10-25 |
| runs recorded as `requested` and dispatched by a worker that survives restarts; caps, priorities, resumable suite runs | [plan-durable-submission.md](plan-durable-submission.md) | plan, implemented (0.7.31) | 2026-10-22 |
| checking SED-ML comparisons against BioSimulators: legacy runs as references, and biosim's `/verify` API as an oracle | [plan-verify-oracle.md](plan-verify-oracle.md) | plan, proposed | 2026-10-22 |
| the web UI at `/ui`: pages, viewers, composite authoring, how it is built | [webapp.md](webapp.md) | user documentation | 2026-10-13 |
| the `compose-api` command line, with its generated reference | [cli.md](cli.md) | user documentation | 2026-10-13 |

**Direction** documents say what we intend. **Analysis** documents measure something and lay out options; they are
dated because measurements go stale. **Record** documents track commitments. When two disagree, the direction
document is the plan of record, and the disagreement should become a dated deviation rather than stay implicit.

The grant text itself (`grant/*.md`, `grant/trd3/*.md`) is git-ignored and exists only on machines where it was
placed by hand; the `tracking/` folder is the versioned part.
