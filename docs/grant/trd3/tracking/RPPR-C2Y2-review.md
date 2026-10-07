# The Year 2 progress report (C2Y2 RPPR), against this repository's goals

**Status (2026-10-07): review written, and the follow-ups in §3 applied the same day.** Analysis, dated. The source
is the Center's Year 2 progress report as drafted before routing (P41EB023912-08; reporting period 04/01/2025 to
03/31/2026; requested budget period 04/01/2026 to 03/31/2027, i.e. Year 3). Like the rest of the grant text, the report
itself is not in this repository; quotes below are verbatim.

[goals.md](../../../goals.md) and the [tracker](TRACKER.md) were written in September from an earlier draft of the same
report. That draft already carried the overall TR&D3 summary, so every Year 2 commitment `goals.md` quotes appears
verbatim in the final text. What the final text adds is TR&D3's own component section: its aims, its three Year 2
activities, its products and its plan for Year 3. This document reads that section against our goals.

## 1. What the report says about TR&D3

**Aims (unchanged).** (1) BioSimulations 2.0: more studies, an expanded simulator registry, a credibility portal.
(2) A composition interface protocol: process interface, composite specification, orchestration methods, an exchange
format. (3) Software tools implementing it. (4) Templates for hybrid and multi-scale simulations.

**Year 2 activities.**

1. **Verification API** (`biosimulations/biosim-server`, client `biosim-client`): compares simulation results across
   simulators; used to verify hundreds of BioModels.
2. **Compose-API working kernel on HPC.** The process bigraph format was completed and submitted, with a public preprint
   (arXiv:2512.23754); an *"HPC-based composition service at UConn"* (this repository); an initial process registry
   with libRoadRunner and COPASI *"available as interoperable simulation services"*; ReaDDy integration initiated with
   the Allen Institute for Cell Science; *"execution of SED2-style simulation experiments on the HPC"*; developed with
   the DARPA Simulating Microbial Systems project, *"which is building a parallel Vivarium-based system that will be
   migrated to the process bigraph standard"*.
3. **SED2 working group**, started after COMBINE with a HARMONY deliverable. Elsewhere the report calls SED2 TR&D3's
   biggest 2026 project: a 25-member working group meeting monthly, led by Eran Agmon with Lucian Smith (TR&D1), demo at
   HARMONY in February 2026.

**Year 3 plan (B.6).** (1) The Composition API, *"testing composition workflows with Collaborative Projects (CPs)"* and iterating on
execution patterns from HPC-scale use cases. (2) The process registry: *"we will add new processes developed internally and
through CPs, including spatial and particle-based simulators"*. (3) Begin the adapter registry: concentrations-to-counts,
unit normalisation, adapters specified as processes.

**Products (C.3)** include process-bigraph, the Verification Service and its client, and *"Compose API (hosted execution
of cosimulation with process bigraph)"* at `https://compose.cam.uchc.edu/docs`.

The External Advisory Board noted that *"Work is ongoing to develop a Compose API"* and raised no TR&D3 concern.

## 2. Against our goals

**Aligned.** [goals.md §4](../../../goals.md) maps the three Year 3 commitments, verbatim, to G1/G2 (Composition API
with CPs at HPC scale), G4 (spatial and particle registry entries) and G5 (adapter registry). G8 quotes the report's
*"design to operational use"*. Strategy decision 4's convergence with `viva-api` matches the report's statement that
SMS will migrate to the standard.

**Progress since the reporting period closed (April to October 2026)** that the Year 3 report can cite:

| Goal | Evidence |
|---|---|
| G2 | Releases 0.6.0, 0.7.0, 0.7.1. Per-run events and traces, datasets, and a simulation listing ([plan-observability.md](../../../plan-observability.md)); a `compose-api` CLI and client covering every operation ([plan-cli.md](../../../plan-cli.md)); an authorization seam ready for Auth0 (#192). |
| G3 | Prebuilt simulators are pinned by image digest, and every run now records its trace and the checksum of each output file. |
| G4 | ReaDDy runs on HPC through this service (tracker `A1.2.readdy`). `viva-pde-particle`, spatial **and** particle-based (Smoldyn coupled to PDE solvers), runs in production as a prebuilt simulator; its full Schaff et al. 2016 single-channel ensemble (138 jobs) ran on mantis and reproduced the locally computed metrics exactly. |

**Gaps.**

1. **SED2 has no goal here.** It is the report's headline TR&D3 effort for 2026, and the report lists, under the kernel,
   *"Enabled execution of SED2-style simulation experiments on the HPC"*. Nothing in this repository documents or tests
   that. SED2 is led outside this repository, so the right shape is a Year 3 evidence row, not a new goal: one SED2
   document executed through compose-api, or a dated note saying why not.
2. **The tracker's grant clock is one month off.** The tracker uses March-to-February years (project period
   03/01/2024 to 02/28/2029). The report's periods run April to March (Year 2 = 04/01/2025 to 03/31/2026).
3. **"The process registry" means two things.** The report's registry is libRoadRunner and COPASI, served by this
   service's `/curated/*` endpoints. This repository's registry is strategy decision 5's manifest, catalog and curation
   ladder. The Year 3 report should say how the first became the second.
4. **ReaDDy's status differs by date, not by fact.** The report says integration was *initiated* (by March 2026); the
   tracker says *delivered* (August 2026). The tracker should say which period a status belongs to.
5. **G1's Collaborating Project is still a placeholder.** The report names two candidates: DARPA SMS and the Allen
   Institute for Cell Science (ReaDDy).
6. **G5 has nothing built.** The adapter registry is a named Year 3 commitment, and strategy phase E is where it lands.

## 3. Follow-ups (applied 2026-10-07; none changes a status)

- [TRACKER.md](TRACKER.md): correct the grant clock to April-to-March years, citing the report's cover page; a dated
  note that the final Year 2 text was checked, with the activities above quoted against rows `A1.3.verify`,
  `A3.2.hosted`, `A1.2.readdy` and `A1.1.sed`; the post-period evidence above added to `A3.2.hosted`, `A1.2.readdy`
  and `A4.1.particle-pde`. Next-step notes only.
- [goals.md](../../../goals.md) §4: a row for SED2 quoting the report, asking for the evidence in gap 1; under G1, the
  two candidate Collaborating Projects, for a person to choose.
- [strategy.md](../../../strategy.md) decision 4: one dated line quoting the report's SMS migration sentence.

## Method

The report PDF was converted with `pdftotext` and read in full for the overall sections, the advisory board's report
and the TR&D3 component; the TR&D1, TR&D2, Administrative and Training components were searched for TR&D3, Compose,
registry and SED2. Each quote above was matched verbatim against the converted text.
