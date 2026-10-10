# Viewers for spatial datasets: registered per dataset type, loaded lazily

**Status (2026-10-10): plan agreed; F1 in progress.** One PR per step, merged on green with a merge commit. Merging to
`main` deploys through Flux (CLAUDE.md, "Deploys are GitOps").

| Step | What | Repo | State |
|---|---|---|---|
| 0 | This document | compose-api | in review (with F1) |
| F1 | Directory datasets (`*.fenics`, `*.zarr`) and `GET /datasets/{id}/files/{subpath}` | compose-api | in review |
| F2 | Viewer registry; built-in viewers; shared bundle reader; `StatsViewer` | compose-api `webapp/` | |
| B1 | Ad hoc `SpatialExport` step and the bundle's `web` extension; the compose runner writes and announces the bundle | viva-pde-particle | |
| B2 | `BundleSurfaceViewer` (vtk.js) | compose-api `webapp/` | |
| A1–A3 | Optional: VCell's vtk.wasm field viewer behind a `DataSource`, fed from the same bundles | vcell, compose-api | later |

## Context
- **Today's preview.** The compose-api web UI (`webapp/`, at `/ui`) previews datasets with a hard-coded chain in
  `DatasetPreview.vue`: image, CSV/TSV, text, whole-file reads up to 5 MB.
- **Spatial output** from PDE/particle runs is the ADR 010 **results bundle** (`*.fenics`), written by vcell-fenics and
  by viva-pde-particle's `viz3d/bundle.py`:
  - a zarr v2 group, with the manifest in its root `.zattrs`
  - `mesh/<domain>.vtu`
  - `<domain>/<var>` arrays of shape (T, N), one zlib chunk per time row
  - `stats/<domain>/<var>` arrays of shape (T, 4)
  - optional `particles/<sp>/xyz`
- **What is missing on each side:**
  - compose-api cannot serve directory datasets.
  - viva-pde-particle's compose runner writes and announces only a `.pber`, never a bundle.

**Goal:** dataset types get registered viewers that load lazily. Viewing needs no dedicated data or render service:
the browser reads static files over HTTP, using standard components where possible. ParaView compatibility is not a
requirement.

## Re-evaluation without ParaView
| Option | Browser data path | Renderer | Verdict |
|---|---|---|---|
| **Bundle + web extension** (chosen) | zarrita reads the bundle chunks directly, one request per time step per variable | vtk.js PolyData (standard), or VCell vtk.wasm (rich) | The bundle is already a shared, static, chunked, documented format (vcell-fenics `docs/results-bundle.schema.json`). No duplication, and live runs are viewable while they run (the manifest is replaced atomically per row). |
| Translate to the vtk.js HttpDataSetSeries layout | stock `HttpDataSetSeriesReader` | vtk.js | The reader is off-the-shelf, but it duplicates every field and needs an end-of-run conversion. Not worth it once ParaView is out of scope. |
| Translate to glTF | three.js or model-viewer | colors baked in | A preview only, with no scalar ranges and no tetra cells. |
| Server API (`viewer_server.py` in compose-api) | JSON endpoints | VCell viewer | A dedicated data service, which the goal excludes. |

**Why a web extension:**
- vtk.js 37 has no unstructured grid and no `.vtu` reader, so a tetra mesh must become a triangle surface before vtk.js
  can draw it.
- Rather than extracting the surface in browser JS, the producer precomputes it once, in the ad hoc step below, as a
  small bundle extension.
- The browser then builds `vtkPolyData` straight from arrays. The field rows are reused as they are: the surface indexes
  mesh points.

## F1. compose-api: directory datasets and a file route
- `compose_api/simulation/job_script.py` `manifest()`: one entry per `*.fenics` or `*.zarr` directory (`find -prune`,
  size via `du -sb`, no sha256), with other files unchanged. Extend the bash test
  `tests/observability/test_job_script.py`.
- `compose_api/observability/datasets.py`:
  - `_KINDS`: `.fenics` → `results-bundle`.
  - `_MEDIA_TYPES`: `.fenics` → `application/vnd.vcell.results-bundle+zarr`, `.zarr` → `application/x-zarr`.
  - `artifact_record` keeps the payload's `view` hint and `media_type` in `attributes`.
- `compose_api/api/routers/datasets.py`:
  - New `GET /datasets/{dataset_id}/files/{subpath:path}`, `operation_id="get-dataset-file"`. Containment reuses
    `resolve_content_path`. `FileResponse` with Range, an ETag and `Cache-Control: no-cache` (live runs rewrite the
    manifest).
  - `/content` on a directory returns 409 (use `/files`) instead of marking the dataset unavailable.
- Client and CLI: `make clients`, a CLI command `compose-api datasets file ID SUBPATH` (`tests/client/test_cli.py`
  requires one), and `make cli-docs`.
- Tests in `tests/api/`: listing, sub-path fetch, `..` and symlink escape, Range, 409.

## F2. webapp: viewer registry
- `webapp/app/viewers/registry.ts` holds `ViewerDef { id, label, icon, match(d): number, load: () => import(...) }`.
  `defineAsyncComponent` gives each viewer and its dependencies (vtk.js, zarrita, wasm) their own chunk, fetched on first
  open (the `PlotlyChart.vue` pattern).
- Port today's previews into built-ins: `ImageViewer`, `TableViewer`, `TextViewer`.
- `DatasetPreview.vue` becomes `DatasetViewer.vue`: rank the matches and offer a viewer switch.
- New page `/ui/datasets/[id]` for deep links. The table modal links to it.
- `useApi.ts` gains `datasetFileUrl(id, sub)` and an auth-aware `fetch` for loaders (reuses `accessToken()`).
- `webapp/app/viewers/bundle/bundle.ts`: a shared zarrita reader for results bundles, used by every bundle viewer.
  - It reads the manifest, rows, `stats/`, `particles/` and `surface/`.
  - It polls the manifest while `status == "running"`.

## B1. viva-pde-particle: an ad hoc translation step (the bundle is the standard we define)
- **New `viva_pde_particle/steps/spatial_export.py`** (the same shape as `steps/transfer.py`).
  - Its job is to make sure a compose run leaves a **viewable bundle**: it finalizes the recorder's bundle and adds the
    web extension.
  - It is not a general converter.
- **Web extension**, an additive bundle extension that existing readers ignore (like the particle extension). It is
  listed in `.zattrs["web"] = {"schema": 1, "surfaces": {...}}`.
  - `surface/<domain>/triangles` (M, 3) uint32 indexes into the domain's mesh points. Boundary faces of tetra domains
    come from faces that appear once, computed with numpy, so no VTK is needed. Membrane and triangle domains use their
    own cells.
  - `surface/<domain>/points` (N, 3) float32, a copy of the mesh points, so the browser never parses VTU.
  - Optional `slice/<name>/{triangles,points,weights}` for a named planar slice, interpolated from mesh rows by stored
    barycentric weights.
- **Document the profile** in `docs/web-bundle.md`, extending ADR 010: the arrays above, plus the `kind` and
  `media_type` compose-api keys viewers on.
- **`compose_runner.py`:**
  - Attach the recorder when the document has spatial output (`viz3d/record.py` `attach_recorder`), and call `close()`
    after `sim.run()`, which the runner never does today. Then run `SpatialExport`.
  - `_announce()` the bundle: `artifact.written`, `kind="results-bundle"`,
    `attributes={format:"vcell-fenics-bundle", web:1, domains, variables, particles}`.
  - Optionally announce a GIF from `viz3d/static.py` as a `figure`.
- **Tests:** fixture bundles from `SpatialBundleWriter`; the extension's triangles cover the boundary (Euler check on a
  cube mesh); runner integration via `compose_runner smoke`.
- **Ship:** rebuild the image and bump the compose-api pin; Flux deploys.

## B2. webapp: standard-component bundle viewers
- **`BundleSurfaceViewer`** for `kind == 'results-bundle'` with `attributes.web` (the default):
  - Built with `@kitware/vtk.js`: `vtkPolyData` from `surface/*` arrays, `vtkMapper` with scalar coloring, a
    `vtkColorTransferFunction` from `stats/`, and particles as a point PolyData from `particles/<sp>/xyz` rows.
  - Controls: domain, variable, time slider (fetches one row), colormap and range (global from stats, or per frame), and
    live-run auto-advance.
  - Works in any WebGL2 browser.
- **`StatsViewer`** for any `results-bundle`, with or without the extension: Plotly mean/total/min/max over time from
  `stats/`.
- Later, for viva-emitters zarr stores: `ZarrViewer`, a group tree plus a Plotly plot of a variable over time.

## A (optional, later). VCell vtk.wasm rich viewer on the same bundles
For volume rendering, clipping, smoothing, picking and kymographs. It is registered next to `BundleSurfaceViewer` for the
same `results-bundle` kind.
- **A1, vcell repo** (`webapp-viewer/viewer.js`):
  - A `DataSource` interface `{info, grid, field, stats, timeseries, kymograph, particles}` replacing `url()`,
    `fetchJson` and 3 `fetch` calls. `HttpDataSource` keeps the loopback behaviour.
  - `mountViewer(el, {source, initial})`.
  - Contract fixtures from `viewer_server.py`.
- **A2, webapp:** `BundleSource` implements `DataSource` on the F2 bundle reader.
  - Reductions (timeseries, kymograph) run in the browser.
  - Port the logic from `viz3d/viewer_server.py`, tested with vitest against the A1 fixtures.
- **A3, webapp:**
  - Lazily load the pinned viewer and the `vcell-vtk-wasm v1.2.0` tarball, fetched at image build into
    `webapp/public/vcell-viewer/` (it must be same-origin).
  - A JSPI check falls back to `BundleSurfaceViewer`.

## Later, when a second producer or a paper figure needs them
- **Standard translation component** (published), for converting between two standard formats only, e.g. voxel zarr →
  OME-Zarr for Viv. Project-specific translation stays in each project's ad hoc step.
- **3D plot / view Step** (published). It emits a **view spec**: JSON that names a target dataset and holds the
  variable, time, surface or slice, camera, colormap and range, particle styling, caption, and the paper figure it
  reproduces. The spec is announced as `kind: "view"` with `attributes.target`. The registry opens the target in the
  best viewer with the spec applied, so a figure can be reproduced by a link.
- Time-major slices in the bundle (a vcell-fenics ADR addendum) for fast point time series and kymographs.

## Order and PRs
1. **F1** in compose-api.
2. **F2** in webapp: the registry, built-ins, the bundle reader, and `StatsViewer`.
3. **B1** in viva-pde-particle, plus the pin bump.
4. **B2** in webapp: `BundleSurfaceViewer`.
5. Optional: **A1–A3**.
6. Later: the items above.

## Verification
- **F1:** pytest and `make check`. After the Flux deploy, `curl /datasets/{id}/files/.zattrs` and a Range fetch of a
  row chunk on a production bundle.
- **B1:** pytest; `compose_runner smoke` in the `compose` env writes a bundle with `web` arrays. A production run then
  lists a `results-bundle` dataset.
- **F2 and B2:**
  - vitest for the bundle reader (manifest, row decode, stats) against fixture bundles.
  - `make webapp-dev` against a local API with fixture datasets. Check in headless Chrome that the surface renders,
    scrubbing time fetches exactly one row chunk per frame (network log), `StatsViewer` plots, and the viewer switch
    lists both.
  - Open a live (still running) bundle and watch it advance.
