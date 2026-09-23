# Internal documentation

**Internal planning, not user documentation.** Everything listed here is planning, analysis and grant material for
the team. This repository is public, so these files are readable by anyone browsing it on GitHub; they are written
with that in mind. They are kept off the published documentation site by `exclude_docs` in `mkdocs.yml`, because
they are not user documentation. The site carries only `index.md` and the generated module reference. If you add a
planning document here, add it to that list.

## Where to start

Several documents answer different questions. Start with the one that matches yours.

| If you want to know… | Read | Kind | Last measured |
|---|---|---|---|
| who this is for, what it must do, and what "done" means | [goals.md](goals.md) | direction, changes rarely | 2026-09-22 |
| how we get there: layering, decisions (toolchain, identity, trust, convergence, simulator wrappers), order, risks | [strategy.md](strategy.md) | direction, changes as decisions land | 2026-09-22 |
| what the grant promised and where we diverged, row by row | [grant tracker](grant/trd3/tracking/TRACKER.md), [deviations](grant/trd3/tracking/DEVIATIONS.md) | record | 2026-09-09 |
| what the composition protocol is and its open design decisions | [CIP design review](cip/CIP-design-review.md), [glossary](cip/GLOSSARY.md) | analysis | 2026-09-09 |
| which libraries and repositories surround this one, and whether we need them all | [ecosystem-repos.md](ecosystem-repos.md) | analysis | 2026-09-12 |
| why container identity should be a digest, and which runtime to run on | [plan-container-runtimes.md](plan-container-runtimes.md) | analysis | 2026-09-12 |
| how testing works, what was broken, what was fixed | [plan-testing.md](plan-testing.md) | analysis, partly implemented | 2026-09-12 |

**Direction** documents say what we intend. **Analysis** documents measure something and lay out options; they are
dated because measurements go stale. **Record** documents track commitments. When two disagree, the direction
document is the plan of record, and the disagreement should become a dated deviation rather than stay implicit.

The grant text itself (`grant/*.md`, `grant/trd3/*.md`) is git-ignored and exists only on machines where it was
placed by hand; the `tracking/` folder is the versioned part.
