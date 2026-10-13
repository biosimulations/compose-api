# Authoring composites in the web app: interface manifests per environment, then an editor

**Status (2026-10-12): plan agreed; step A in review.** One PR per step, merged with a merge commit on the
maintainer's word. A merge deploys nothing by itself: the next release's image ships it (CLAUDE.md, "Deploys are
GitOps"). The language side is planned in process-bigraph-lang's
[`docs/v2/authoring-plan.md`](https://github.com/biosimulations/process-bigraph-lang/blob/main/docs/v2/authoring-plan.md).

| Step | What | Repo | State |
|---|---|---|---|
| 1 | A standalone describe script; a shared manifest format (`pbg-interfaces/1`) with a JSON Schema; a replaceable registry and a `pblang/setManifests` channel in the language worker | process-bigraph-lang | in review (#56) |
| A | Environments, their manifests generated in CI inside each image, `/registry/environments`; viva-pde-particle as a registry entry; these docs | compose-api | in review (#270) |
| B | The composite viewer checks against the run's environment, so processes resolve | compose-api `webapp/` | in review (#271) |
| C | An editor: language worker, environment picker, compile, submit | compose-api `webapp/` | in review |
| R | process-bigraph-lang 0.2.0; compose-api bumps it and releases A, B and C together | both | planned |

## Why

Stage one shipped in 0.7.12 and 0.7.13: a submitted `.pbg` opens as `.pblang` text and a wiring graph
([webapp.md](webapp.md)). Every process in it is reported "not in the registry", because the browser knows no
process interfaces. An editor needs them twice: in the main-thread session (check, compile, graph) and in the
language worker (hover, completion, diagnostics while typing).

## Decisions (2026-10-12)

- **A manifest describes an environment, not a package.** Ports and config schemas are what the classes declare
  *in the image that runs the document*, and the images differ: `registry_env` carries process-bigraph 1.0.5 through
  pbest, viva-pde-particle's image 1.8.x and its own core. Describing a package in some other environment would
  describe classes this service does not run.
- **Manifests are produced here, in CI, inside each image**, not by image owners and not lazily on HPC. The
  `registry-manifests` workflow runs process-bigraph-lang's describe script in every environment this deployment
  offers and opens a pull request when a manifest changes. That keeps them reviewed, like `catalog.yaml`, needs
  nothing from image owners, and is the first concrete output of strategy decision 5's phase B.
- **The format is shared, not this service's or the DSL's**: `pbg-interfaces/1`, with a published
  [JSON Schema](https://biosimulations.github.io/process-bigraph-lang/schemas/pbg-interfaces-1.schema.json). Types
  are bigraph-schema's own forms and addresses process-bigraph's, as the classes declare them, so the workbench, a
  skill or another checker can read the same files.
- **The web app gets them from this API, same origin**: `GET /registry/environments` and
  `GET /registry/environments/{name}/manifest`, through the typed client. They are not baked into the static build.
  They ship in the API image with the other registry files, so a regenerated manifest goes live with the next release.
- **viva-pde-particle is a registry entry** (`tested`, bundle `viva-pde-particle`), so the components its manifest
  lists belong to an entry with a level. Its bundle is its own: a submission without `simulator=viva-pde-particle`
  still refuses its addresses, as before.

## Step A: what exists after it

- `compose_api/registry/environments.yaml`: the environments (`registry_env`, shared; `viva-pde-particle`,
  prebuilt), how to enter each one's Python, and the describe script's pinned commit. The modules described are the
  `module_roots` of the entries whose `bundles` name the environment; the image is the one the service uses (the
  shared image's definition hash, or the `PREBUILT_SIMULATORS` pin).
- `python -m compose_api.registry.generate [--env NAME] [--describe PATH]`: pulls the image (building the shared one
  from its generated Dockerfile when that tag is not published, which today it is not: see
  [plan-container-runtimes.md](plan-container-runtimes.md) §4.4), runs the describe script in it through the
  environment's own Python, and writes `compose_api/registry/manifests/<name>.json`. Runs anywhere Docker does.
- `.github/workflows/registry-manifests.yml`: one job per environment; on a pull request the manifests are uploaded
  as artifacts, otherwise a pull request is opened when one changed (weekly, on demand, and when the registry, the
  shared library list or the deployment's pins change). Opening pull requests needs "Allow GitHub Actions to create
  and approve pull requests" in the repository settings.
- `GET /registry/environments`: per environment, its `simulator` value for `/simulation/run` (null for the shared
  image), the deployed image, the image the manifest was read from, `stale` when they differ, counts, and its
  registry entries with their levels. `GET /registry/environments/{name}/manifest`: the manifest, each component with
  its `registry_entry` (id and level), with an ETag. `GET /registry/environments/{name}/headers`: the same classes as
  `.pblang` header files, one per module, and each class's declaration by address, printed by process-bigraph-lang
  (`settings.pblang_python`) and cached per manifest; CLI `environments headers [-o dir]`. The environment page shows
  each class's header (with its `import` line) and manifest entry, and downloads every module as one `.pblang` file.
- Tests (`tests/registry/test_environments.py`) check the configuration, the docker command, the summaries, the
  routes, and that every committed manifest was read from the deployed image and lists only registered components.

## Steps B and C

- **B.** A `useRegistry()` composable lists environments and fetches a manifest, cached per name. The composite
  viewer takes the environment from the run (`simulator`, else `registry_env`) and adds its manifest before checking
  and graphing.
- **C.** A page to write a composite (and "edit a copy" from the viewer). An environment picker feeds the session
  (`setManifests`) and the worker (`pblang/setManifests`). Monaco is editable, with the language worker connected by a
  thin JSON-RPC client (diagnostics as markers, hover, completion). Compile, then submit the document as a `.pbg` to
  `/simulation/run` with the environment's `simulator`, through a submit composable shared with the existing form.
- **The address form (settled in C).** Manifests address classes as `local:!module.Class` (process-bigraph's import
  form). This service always refuses that form at submission and accepts `local:module.Class` under a registered
  entry (CLAUDE.md, "Registry and submission checks"); process-bigraph's discovery registers every class under that
  name, and viva-pde-particle's runner does too. The editor compiles with process-bigraph-lang's
  `addresses: "registered"`, which writes `local:module.Class` everywhere a class is addressed.
- **What C delivered.** `/ui/composites/new` (and "Edit a copy" in the viewer, which opens a run's composite in the
  environment it ran in, sidecar files included). The language worker runs in a web worker behind a thin client
  (`webapp/app/viewers/composite/languageClient.ts`: text sync, markers, hover, completion; Monaco's hover and suggest
  contributions are registered in `monaco.ts`, since `editor.api` is the bare editor). Run compiles in the browser
  and submits through `useSubmitRun`, which the run form shares. Open sites and params have no form yet: the checker
  reports an unfilled one, and the text is edited to fill it.

## Out of scope

Port checking at submission (the service still checks addresses only), the address check for prebuilt submissions,
manifests for `listed` catalog entries (no environment of ours carries them), units and contracts in manifests,
the per-composite resolver (phase C of decision 5), retiring the Postgres `/core/*` catalog.
