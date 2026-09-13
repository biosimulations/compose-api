# Goals

**Status:** draft, opened 2026-09-13. This is the statement of who the system is for, what it must do, and what
"done" looks like. It changes rarely. It is written to be readable by the External Advisory Board, and it is the
document the Year 3 progress report is checked against. How we get there is in [strategy.md](strategy.md).

Every goal below traces to a row in the [grant tracker](grant/trd3/tracking/TRACKER.md) and, where one exists, to a
sentence from the Year 2 report quoted verbatim. That is deliberate: the goals are a commitment to a funder as much as
a plan for ourselves.

---

## 1. Who it is for

**The primary user is a researcher on a Collaborating Project.** They install one Python toolkit, build a composite
simulation on their own machine, run it there, and then submit the *same* composite to HPC without changing it. The
command-line toolkit is the product they touch; the hosted service is its backend. This follows the grant's framing
of Collaborating and Service Projects as the audience, and the advisory board's repeated emphasis on engagement with
them.

**Two secondary users consume the same service through other doors.** Workbench users compose visually and never
see Python. Web users arrive through the BioSimulations front end. Both reach this service through the same API
contract the toolkit uses, and the goals below hold for them too. The contract is what keeps the three from drifting
apart.

**Who it is not yet for.** Anyone who needs to run code we have not registered. See goal G6 and the non-goals.

---

## 2. What it must do

Eight goals. Each is one sentence, then its trace.

**G1. A collaborating project can install the toolkit and run a composite locally, then submit it to HPC
unchanged.**
Trace: tracker `A3.4.pypi` (delivered), `A3.2.hosted` (deviated; see D2). Year 2 committed to validating the
*"Composition API through real composite simulations with Collaborative Projects and HPC-scale use cases"*.

**G2. The hosted service can be relied on: a request for something that does not exist says so, a job that fails
says so, and nothing fails silently.**
Trace: `A3.2.hosted`. This is the product the Year 2 report named: *"Compose API (hosted execution of cosimulation
with process bigraph)"*.

**G3. A result is reproducible years later: every simulation records the exact image digest it ran in, and that
image can be fetched and re-run.**
Trace: `A1.1`, `A2.2`. The case for digest identity is made in
[plan-container-runtimes.md §1](plan-container-runtimes.md).

**G4. The process registry grows to include spatial and particle-based simulators, each independently versioned and
independently rebuildable.**
Trace: `A1.2.readdy`, `A1.2.cpm`, `A1.2.mem3dg`, `A1.2.cellpack` and siblings. Year 2 committed:
*"The process registry will be expanded to include additional simulators, including spatial and particle-based
tools, creating a growing catalog of interoperable components."*

**G5. An adapter registry exists, with unit normalisation and concentration-to-count conversion available as
processes a composite can wire in.**
Trace: `A3.3e` (in-progress). Year 2 committed: *"development of an adapter registry will begin, targeting common
translation challenges such as unit normalization and conversions between concentrations and counts."*

**G6. In this funding year, composites execute only registered simulators; running arbitrary user-supplied code is a
stated later goal with a stated trigger.**
Trace: `A3.4.docker` (in-progress). This is an access-control boundary, not a security boundary, and this document
says so plainly rather than implying isolation that does not exist.

**G7. There is one execution backend, whichever front door a user arrives through.**
Trace: `A3.2.hosted`, deviation D2. Today there are two hosted composition backends. Converging them is a goal, and
[strategy.md](strategy.md) decision 4 says how to begin.

**G8. The operational deployment tracks the composition standard's reference implementation, so that what we run is
what we published.**
Trace: `A3.2` (delivered), `A2.spec`. Year 2 reported the Compose-API kernel as *"marking the transition of the
process bigraph composition standard from design to operational use"*. That sentence is only true while the
deployment keeps pace with the standard.

---

## 3. What done looks like

Each goal has an observable test. If the test cannot be run, the goal is not done.

| Goal | Done means |
|---|---|
| G1 | A named collaborator, not a member of this team, installs the toolkit from PyPI on a clean machine, runs a composite locally, submits the identical file to HPC, and gets the same result back. Documented as a walkthrough they followed, not one we wrote for them. |
| G2 | The API returns 404 for absent resources and 5xx only for server faults; a job the scheduler reports as failed is recorded as failed within one polling interval; the test suite covers these without a real cluster. Most of this landed in September 2026. |
| G3 | Pick any simulation from 2026. Its record names an image digest. Pulling that digest and re-running the composite reproduces the result to the tolerance the tests use. |
| G4 | Each registered simulator is its own image with its own digest; adding one does not rebuild the others; the registry lists at least one particle-based and one spatial simulator beyond what exists today. |
| G5 | A composite that wires a concentration-emitting process to a count-consuming process runs correctly through a registered adapter, with no hand-written glue in the composite. |
| G6 | The service rejects a composite naming an unregistered process address with a clear message, and the goals for the untrusted tier are written down with their trigger. |
| G7 | A composite submitted through either front door runs on the same backend, or the strategy document records a dated decision that they will stay separate and why. |
| G8 | `uv.lock` here resolves the same `process-bigraph` minor version the workbench ecosystem resolves, and a scheduled check fails when it drifts more than one minor version. |

---

## 4. Year 3 specifically

Year 2 made three forward commitments. They map to goals as follows, with what the Year 3 report will need to show.

| Year 2 commitment (verbatim) | Goal | Evidence Year 3 must produce |
|---|---|---|
| *"further development and validation of the Composition API through real composite simulations with Collaborative Projects and HPC-scale use cases"* | G1, G2 | One real composite from one named Collaborating Project, run end to end on HPC through the toolkit, with the collaborator's walkthrough. |
| *"The process registry will be expanded to include additional simulators, including spatial and particle-based tools"* | G4 | ReaDDy (particle-based) is already registered. At least one spatial simulator added and one composite that uses it. Which ones, named in advance in the tracker. |
| *"development of an adapter registry will begin, targeting common translation challenges such as unit normalization and conversions between concentrations and counts"* | G5 | The adapter category exists in the registry with at least the two named adapters, and one composite uses one of them. |

**A framing point for the report.** Both prior reports cite repository counts as evidence of output. This year the
toolchain is being consolidated, which lowers that number. The report should count tools delivered and maintained,
and should say that consolidation was a maturity decision made to reach production quality. The advisory board has
already shown it values that reasoning: it praised a sibling tool because it *"requires no installation or ongoing
server maintenance costs"* and said that *"this will increase the chances for the tools' survival after the grant is
over."*

---

## 5. Non-goals, stated

Things this project is explicitly not trying to do in this funding year, so that nobody has to infer them.

- **Executing arbitrary user-supplied code.** Planned for, not built. Trigger: the day a composite can carry a
  process a collaborator wrote rather than one we registered. See G6 and
  [plan-container-runtimes.md §4.2](plan-container-runtimes.md).
- **GPU or multi-node execution.** No current workload requests either: the production jobs ask for one or two CPUs
  and one to eight gigabytes on one node. This is measured, not assumed, and it would change if a collaborator
  brought such a simulator.
- **Consolidating the ~50 simulator-wrapper repositories.** They have separate upstreams, licences and release
  cadences, and a generated index already makes them addressable. See [ecosystem-repos.md](ecosystem-repos.md).
- **Renaming this repository in this cycle.** It will hold more than an API once the toolkit moves in, and a broader
  name is reasonable, but a rename touches a permanent identifier (the Zenodo concept DOI) and is a separate
  decision.
- **An XML serialisation of the exchange format.** Set aside in the CIP design review.

---

## 6. How this document is used

When the Year 3 report is drafted, each claim in it should point at a goal here and at the evidence in §3 or §4. When
a goal is met, the row in §3 is updated with the date and a link to the evidence. When a goal changes, the change is
recorded in [DEVIATIONS.md](grant/trd3/tracking/DEVIATIONS.md) with a reason, not edited silently. Strategy, phases
and risks live in [strategy.md](strategy.md) and change more often than this file does.
