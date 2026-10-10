# Web UI

A proof-of-concept browser UI for this API lives in `webapp/`. It is a static single-page app built with
Nuxt 4, Nuxt UI 4 and Tailwind v4, the same stack as the BioSimulations platform frontend
(`biosimulations/platform`, `frontend/`), whose shell, theme and page patterns it adapts. The API
serves it at **`/ui`** on the same host, and `/` redirects there.

## What it covers

| Page | API operations |
|---|---|
| `/ui/` dashboard: counts by status, recent runs | `list-simulations`, `/version` |
| `/ui/simulations`: paged and filterable by status, simulator and date; download `results.zip` | `list-simulations`, `get-simulation-results-file` |
| `/ui/simulations/new`: upload a `.pbg`, `.omex` or `.sbml`, or a curated COPASI/Tellurium time course from SBML. Registry rejections are listed address by address | `run-simulation`, `run-copasi`, `run-tellurium` |
| `/ui/simulations/{id}`: status (polled until terminal), SLURM and container-build details, live event log, span tree and Chrome trace (for Perfetto), datasets with inline previews (images, CSV/TSV plotted with Plotly, JSON, text) | `get-simulation`, `get-simulation-status`, `get-simulator-build-status`, `get-simulation-events`, `get-simulation-trace`, `get-simulation-trace-chrome`, `list-datasets`, `get-dataset-content`, `get-simulation-results-file` |
| `/ui/datasets`: every run's files | `list-datasets`, `get-dataset-content` |
| `/ui/catalog`: processes, steps, simulator versions | `get-processes-list`, `get-steps-list`, `get-simulator-list` |

**Viewers are registered per dataset type** (`webapp/app/viewers/registry.ts`, [plan](plan-viewers.md)). Each one
declares which datasets it fits (by kind, media type and attributes) and is an async component, so a viewer and its
libraries download only when first opened. `/ui/datasets/<id>` opens a dataset full width; the table's preview shows
the same viewers. Built in: image, table (plotted when numeric), text, and for results bundles (`*.fenics`) a
statistics view and a **3D view** (vtk.js) read chunk by chunk with zarrita from `/datasets/{id}/files/`. The 3D view
draws the bundle's web extension (a precomputed surface per domain, viva-pde-particle `docs/web-bundle.md`) coloured by
one variable, fetches one row per frame, shows particles, and follows a running simulation.

`get-simulations-status-batch` is not used: it is a GET with a JSON body, which browsers cannot send. The list page
re-fetches while any row is still running.

## How it is built and served

- `npm run generate` writes static files to `webapp/.output/public`. The image builds them in a Node stage of
  `Dockerfile-api` and copies them in.
- `compose_api/api/webapp.py` mounts that directory at `/ui` when it exists (`settings.webapp_dist_dir`). A path
  without a file suffix gets the app shell (`200.html`), so deep links work. Without a build, the API runs as
  before.
- The API calls are typed from the committed OpenAPI spec. `npm run types` (also run by `make clients`) regenerates
  `webapp/app/api/schema.d.ts` with `openapi-typescript`, and the calls go through `openapi-fetch`. CI fails if that
  file is stale. Never hand-edit it.
- There is no ingress change: the existing `/` → `api:8000` rule already covers `/ui`.

## Sign-in

The API accepts anonymous calls ([Authentication](authentication.md)), so the UI works without signing in. The UI
offers an Auth0 login (`@auth0/auth0-vue`, after the platform frontend's plugin) only when the API publishes all
three of these at `GET /webapp/config`:

| Setting | Meaning |
|---|---|
| `AUTH0_DOMAIN` | the tenant, shared with token verification |
| `AUTH0_AUDIENCE` | the API identifier the UI requests a token for |
| `AUTH0_SPA_CLIENT_ID` | an Auth0 **Single Page Application** whose allowed callback, logout and web origins include `https://compose.cam.uchc.edu/ui/` (and `http://localhost:4200/ui/` for development), and which may request that audience |

Rules for the token:

- Only API requests carry it.
- When the API rejects it (401), the UI drops it, carries on anonymously, and shows a banner. It does not retry.
- Downloads by a signed-in user are fetched with the token, because a plain link cannot carry the header.

Today a token changes nothing a caller can read, because every simulation is public.

## Development

```bash
make webapp-install       # npm ci (Node 24, see webapp/.nvmrc)
make run                  # the API on :8000
make webapp-dev           # the UI on http://localhost:4200/ui/, calling the API on :8000
COMPOSE_API_URL=https://compose.cam.uchc.edu make webapp-dev   # against production instead (CORS allows :4200)
make webapp-check         # lint, typecheck, API types current
make webapp-build         # static build; `make run` then serves it at http://localhost:8000/ui/
```

`npm audit` reports advisories in build-time tooling (the Nitro dev server and its dependencies). None of it ships:
the image serves only the generated static files.

## Toward one frontend with the platform

The platform frontend is server-rendered and deployed on GKE (`biosim.biosimulations.org`). This UI is static and
served by the API on the on-premise RKE2 cluster (`compose.cam.uchc.edu`). Because they share a stack, components
move between the two without rewriting. There are two ways to reconcile them:

1. **The platform frontend gains a compose backend.** These pages become a section of the platform app with a
   configurable base URL for this API, and `/ui` here is retired. This needs CORS for the platform origin and the
   same Auth0 audience setup.
2. **Nuxt layers.** These pages ship as a Nuxt layer that both apps extend: the platform app on GKE, and a thin
   shell here for the on-premise deployment.
