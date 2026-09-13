# compose-api

[![Release](https://img.shields.io/github/v/release/biosimulations/compose-api)](https://img.shields.io/github/v/release/biosimulations/compose-api)
[![Build status](https://img.shields.io/github/actions/workflow/status/biosimulations/compose-api/main.yml?branch=main)](https://github.com/biosimulations/compose-api/actions/workflows/main.yml?query=branch%3Amain)
[![Commit activity](https://img.shields.io/github/commit-activity/m/biosimulations/compose-api)](https://img.shields.io/github/commit-activity/m/biosimulations/compose-api)
[![License](https://img.shields.io/github/license/biosimulations/compose-api)](https://img.shields.io/github/license/biosimulations/compose-api)

An API server for reproducible biological workflows and cosimulations.

## Where to start

There are several documents here and they answer different questions. Start with the one that matches yours.

| If you want to know… | Read | Kind | Last measured |
|---|---|---|---|
| who this is for, what it must do, and what "done" means | [goals.md](goals.md) | direction, changes rarely | 2026-09-13 |
| how we get there: layering, decisions, order, risks | [strategy.md](strategy.md) | direction, changes as decisions land | 2026-09-13 |
| what the grant promised and where we diverged, row by row | [grant tracker](grant/trd3/tracking/TRACKER.md), [deviations](grant/trd3/tracking/DEVIATIONS.md) | record | 2026-09-09 |
| what the composition protocol is and its open design decisions | [CIP design review](cip/CIP-design-review.md), [glossary](cip/GLOSSARY.md) | analysis | 2026-09-09 |
| which libraries and repositories surround this one, and whether we need them all | [ecosystem-repos.md](ecosystem-repos.md) | analysis | 2026-09-12 |
| why container identity should be a digest, and which runtime to run on | [plan-container-runtimes.md](plan-container-runtimes.md) | analysis | 2026-09-12 |
| how testing works, what was broken, what was fixed | [plan-testing.md](plan-testing.md) | analysis, partly implemented | 2026-09-12 |
| the code itself | [modules.md](modules.md) | reference | generated |

**Direction** documents say what we intend. **Analysis** documents measure something and lay out options; they are
dated because measurements go stale. **Record** documents track commitments. When two disagree, the direction
document is the plan of record, and the disagreement should become a dated deviation rather than stay implicit.
