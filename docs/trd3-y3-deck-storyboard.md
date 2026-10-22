# TR&D3 Year 3: storyboard for a 20-minute advisory-board talk

**Audience.** The External Advisory Board.

**Length.** 20 minutes, 15 slides: 18.5 minutes of talk plus 1.5 minutes of slack for the live demo on slides 5–7.

**Source.** [Y3-progress-outline.md](trd3-y3-progress-outline.md). Every claim on a slide comes from there with its
evidence, and the numbers are re-queried on the day (see its "Numbers" table).

**Arc.** What we promised → what now runs → evidence that it is credible → status, stated plainly → what comes by
March 2027.

The board has asked, over two years, that we:

- extract data from the portal;
- attribute failures carefully;
- track use;
- disseminate.

Slide 3 answers each of these by name, and the rest of the talk carries the evidence.

**Demo policy.** Slides 5–7 use screenshots, and each slide links to the live page. Demo live only if the network
allows, and never wait on a run: show runs that have already completed.

---

## Slides

### 1. TR&D3: composition you can reproduce (0.5 min)

- **Message:** TR&D3 builds the tools that let a modeler compose simulators and get the same answer anywhere.
- **Visual:** Title; team (Schaff, Agmon, Valencia, Burr, Drescher, others **[to fill]** from the Year 3 participants);
  logos of the Center, UConn, and the University of Florida (BioModels).
- **Say:** One line on the grant's TR&D3: BioSimulations 2.0, the composition protocol, tools, templates.

### 2. What we promised for Year 3 (1.0 min)

- **Message:** Year 2 made three commitments for Year 3, and SED2 is a fourth. They are this talk's checklist.
- **Visual:**
  - A strip of Aims 1–4.
  - A four-row checklist, left unmarked until slide 13:
    1. Composition API with collaborating projects at HPC scale;
    2. spatial and particle-based registry;
    3. adapter registry;
    4. SED2 v1.
- **Say:** Quote each commitment in its own words, briefly.

### 3. What we did with your advice (1.0 min)

- **Message:** The board's recommendations from 2024 and 2025 changed what we built.
- **Visual:** A table pairing each recommendation with what we did and where it appears:

  | Recommendation | What we did | Slide |
  |---|---|---|
  | Let users extract data tables | Every run's outputs are datasets (CSV, figures, zarr, downloads) | 6 |
  | Attribute failures carefully: the wrapper may be at fault, not the model | The suites traced disagreements to solver steps, not models | 8 |
  | Track users and impact | Labels and tags on runs, run counts, Zenodo DOIs | 6, 13 |
  | Disseminate | Packages, public docs, archives, talks | 11, 13 |
  | Build automated wrapper generation | Interface manifests generated inside each image, and checked | 5 |

- **Say:** Close the loop the Year 2 response opened on dissemination, without dwelling on it. The evidence is in the
  table.

### 4. From prototype to production (1.5 min)

- **Message:** A composite now goes from text to checked document to HPC run to comparable results, every step
  recorded.
- **Visual:** An architecture diagram, drawn new:
  1. `.pblang` editor in the browser;
  2. checker against the environment's interface manifest (`pbg-interfaces/1`);
  3. compose-api (Kubernetes) submits to the Mantis SLURM cluster, in an image pinned by digest;
  4. events, trace and datasets are recorded;
  5. comparisons and suites run on a schedule.

  Side labels: "registered addresses only (G6)" and "image digest = identity (G3)".
- **Say:**
  - 4,428 runs since April.
  - Releases 0.4 → 0.7.25.
  - Deploys are GitOps.
  - Each release is archived on Zenodo.

### 5. A composite is checked before it runs (1.5 min)

- **Message:** Mistakes in wiring, types, units and config are caught as you type, against the processes the
  environment really provides.
- **Visual:** Two screenshots:
  1. the composite editor with a finding underlined and its hover (`/ui/composites/new?from=<dataset>`);
  2. the environment page with a class's `.pblang` header (`/ui/environments/registry_env#CopasiUTCProcess`).
- **Say:**
  - This is the grant's "static composite checker" (Aim 3, Task 3.3a).
  - process-bigraph-lang is one grammar and checker serving the command line, editors and the browser.
  - It is on PyPI and npm.

### 6. Every run is observable, and its results reusable (1.5 min)

- **Message:** Each run explains itself (what ran, where, how long, what it produced), and its results can be
  downloaded.
- **Visual:** Three screenshots:
  1. the Perfetto trace, opened already loaded from `/ui/simulations/4553?tab=trace`;
  2. the run's datasets tab;
  3. the 3D results viewer (viva-pde-particle).
- **Say:** Answers "extract data tables". Labels make runs queryable by source, model, solver and suite.

### 7. One model, several solvers, one verdict (2.0 min)

- **Message:** A published SED-ML study runs on COPASI and Tellurium as process-bigraph composites, and agrees with
  its original results.
- **Visual:**
  - the comparison page for Ciliberto et al. 2003 (`/ui/comparisons/39`): overlaid plots, with each solver dashed and
    the original in grey, and the score matrix;
  - the score formula as a small footnote;
  - "worst score 0.019 (< 1 is close)".
- **Say:**
  - SED-ML is translated by process-bigraph-lang into a template with the solver left open, then checked for each
    solver.
  - The plots come from the composite itself.
  - It reuses the BioSimulations verification score (the *PLoS Comput Biol* 2025 paper).

### 8. Credibility catches real defects (1.5 min)

- **Message:** Run on a schedule against a baseline, the suites find defects, and they find them in the solver
  wrappers, not in the models.
- **Visual:**
  - The suite page: a grid of models × solvers, green, amber (expected failure, with its reason) and red.
  - Three call-outs: Tellurium with assignment-rule species; Tellurium with events (Edelstein); COPASI on a model with
    no species.
  - An inset showing the same archive with a tightened tolerance turning red.
- **Say:**
  - The Year 1 board warned that the wrapper may be at fault; here is the instrument that tells which.
  - One disagreement (BIOMD0000000043) is still open, and we say so.

### 9. Hybrid particle/PDE at HPC scale (1.5 min)

- **Message:** A spatial hybrid (Smoldyn particles with PDE solvers) reproduces Schaff et al. 2016, and its full
  ensemble on HPC matches the local runs exactly.
- **Visual:** A figure from the viva-pde-particle dashboard
  (<https://vivarium-collective.github.io/viva-pde-particle/dashboard/>), plus "138 SLURM jobs, metrics identical to
  local".
- **Say:**
  - Tracker A4.1.particle-pde, a grant Table 1 hybrid.
  - It runs in production from its own image.
  - It is benchmarked against the hybrid solver inside VCell's finite-volume code.

### 10. A growing registry of trusted processes (1.0 min)

- **Message:** The process registry now includes spatial and particle-based simulators, each at a measured curation
  level.
- **Visual:** The catalog and environments pages: 52 entries (4 `tested`), 2 environments, 2 SED-ML solvers; ReaDDy,
  pb-multiscale-actin, viva-pde-particle highlighted.
- **Say:**
  - This meets Year 2 commitment 2 (G4).
  - Wrappers in progress with Agmon's group: MEDYAN, Mem3DG, cellPACK.
  - Cellular Potts is delivered.

### 11. Standards: from code to community (1.5 min)

- **Message:** The composition protocol runs in production. Its readable, checkable form now exists, and the written
  specification comes next.
- **Visual:**
  - Three tiles: `pbg-interfaces/1` (JSON Schema), `.pblang` (a snippet), the process-bigraph preprint
    (arXiv:2512.23754);
  - a SED2 working-group tile (25 members, monthly; **[to fill]**: the HARMONY 2026 demo).
- **Say:**
  - D1, stated openly: the protocol exists as code, and a versioned specification goes to HARMONY 2027.
  - SED2 is co-led with TR&D1.

### 12. The BioSimulations portal, renewed (1.0 min)

- **Message:** The portal is being rebuilt for durability, and verification results are published.
- **Visual:**
  - screenshots of the platform beta (<https://biosim.biosimulations.org>): project search, a run page;
  - the citation of the verification paper (1,073 BioModels entries, 5 simulators).
- **Say:**
  - D2: composite runs live on the Compose API.
  - The decision on one front door or two (G7) comes by March 2027.

### 13. Scorecard against the grant (1.0 min)

- **Message:** Most commitments are delivered or under way. The rest are named, with reasons.
- **Visual:**
  - the slide 2 checklist, now marked: met, met, not yet begun, **[to fill]**;
  - the tracker roll-up as one bar each for 2026-09-09 and 2026-10-13 (delivered 7 → 9);
  - D1–D3 in one line each.
- **Say:** Overdue items, stated plainly: the ODE/SSA and FBA/Boolean templates (due in Year 2), and Cytosim.

### 14. By March 2027 (1.5 min)

- **Message:** Five deliverables close the Year 3 commitments and the overdue items.
- **Visual:** A timeline from November 2026 to March 2027:
  - adapter registry (Nov);
  - solver-step fixes and rebaseline (Nov);
  - ODE/SSA and FBA/Boolean templates (Dec);
  - BioModels corpus with Sego's walkthrough (Dec);
  - SED2 document through the service (Jan);
  - CIP specification at HARMONY (Feb);
  - front-door decision (Mar).
- **Say:** Each item names the goal it closes. The dates are targets.

### 15. Asks and risks (0.5 min)

- **Message:** Three dependencies decide Year 4.
- **Visual:** Three boxes:
  - TR&D1 credibility libraries (the credibility portal, Years 3–4);
  - TR&D2 annotations (composition from annotations);
  - an outside user running end to end (G1, BioModels).

  Footnote: operational risk of lost submissions (#238), with a fix planned.
- **Say:** End on the checklist. Then questions.

---

## Screenshots to capture (live, the day before)

| Slide | Page | State |
|---|---|---|
| 5 | `/ui/composites/new?from=<input dataset of a SED-ML run>` | a deliberate wiring error underlined, its hover open |
| 5 | `/ui/environments/registry_env#CopasiUTCProcess` | header open |
| 6 | `/ui/simulations/4553?tab=trace`, then **Perfetto** | trace loaded in Perfetto |
| 6 | a completed run's datasets tab | table with a CSV and a figure |
| 6 | a viva-pde-particle run, 3D viewer | a mid-run frame |
| 7 | `/ui/comparisons/39` | plots overlaid, matrix visible |
| 8 | `/ui/suites/biomodels-ode-sample` and the tightened-tolerance comparison | grid with amber cells |
| 9 | viva-pde-particle dashboard | Test 3–5 metrics figure |
| 10 | `/ui/catalog`, `/ui/environments` | — |
| 12 | <https://biosim.biosimulations.org> | project search, a run page |

Capture with the Playwright scripts already used for the web app's checks, at 1600×1000, light theme.

## Before the talk

- Re-query the numbers in the outline's table, and update slides 4, 10 and 13.
- Fill every **[to fill]**: team list, SED2 and HARMONY status, talks, the collaborating projects' status.
- Rehearse to 18.5 minutes.
