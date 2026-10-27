# Web UI

A proof-of-concept browser UI for this API lives in `webapp/`. It is a static single-page app built with
Nuxt 4, Nuxt UI 4 and Tailwind v4, the same stack as the BioSimulations platform frontend
(`biosimulations/platform`, `frontend/`), whose shell, theme and page patterns it adapts. The API
serves it at **`/ui`** on the same host, and `/` redirects there.

## What it covers

| Page | API operations |
|---|---|
| `/ui/` dashboard: counts by status, recent runs | `list-simulations`, `/version` |
| `/ui/simulations`: paged and filterable by status, simulator, date, labels (`key:value`) and tags; label and tag chips filter the list; where each run ran ("Ran in"), and the runs of one environment, version or simulator (linked from their pages); download `results.zip` | `list-simulations`, `get-simulation-results-file` |
| `/ui/simulations/new`: upload a `.pbg`, `.omex` or `.sbml`, or a curated COPASI/Tellurium time course from SBML. Registry rejections are listed address by address | `run-simulation`, `run-copasi`, `run-tellurium` |
| `/ui/simulations/{id}`: where it ran (its environment version, or its simulator for a run from before versions), status (polled until terminal), SLURM and container-build details, live event log, span tree and Chrome trace (for Perfetto), datasets with inline previews (images, CSV/TSV plotted with Plotly, JSON, text) | `get-simulation`, `get-simulation-status`, `get-simulator-build-status`, `get-simulation-events`, `get-simulation-trace`, `get-simulation-trace-chrome`, `list-datasets`, `get-dataset-content`, `get-simulation-results-file` |
| `/ui/datasets`: every run's files | `list-datasets`, `get-dataset-content` |
| `/ui/datasets/{id}`: one dataset full width in its viewers (a results bundle file by file) | `get-dataset`, `get-dataset-content`, `get-dataset-file` |
| `/ui/composites/new`: write a composite in `.pblang`, checked as you type, and run it (below) | `list-environments`, `get-environment-manifest`, `run-simulation` |
| `/ui/sedml`: a SED-ML archive (upload, BioModels, biosimulations.org) previewed and run on several solvers ([plan-sedml.md](plan-sedml.md)) | `preview-sedml`, `run-sedml`, `search-biomodels`, `get-biomodel-omex`, `run-biomodel`, `search-biosimulations-projects`, `get-biosimulations-omex`, `run-biosimulations-project`, `list-solvers` |
| `/ui/comparisons`, `/ui/comparisons/{id}`: a task's runs, scores per report and data set, overlays of data sets and SED-ML plots | `list-comparisons`, `get-comparison`, `get-comparison-series`, `list-datasets`, `get-dataset-content` |
| `/ui/suites`, `/ui/suites/{name}`: regression and reproducibility suites, their runs (each with the environment versions it ran in), agreement, references and drift from the baseline per model; "Run the suite" (signed in) picks a version of each environment its solvers use and confirms first; with `suites:curate`, mark, edit and clear each solver's known problems, each confirmed ([plan-known-problems](plan-known-problems.md)) | `list-suites`, `list-suite-runs`, `get-suite-run`, `run-suite`, `list-solvers`, `list-environment-versions`, `list-suite-problems`, `mark-suite-problem`, `edit-suite-problem`, `clear-suite-problem` |
| `/ui/environments`: where composites run, and the simulators runs used before environments had versions; `/ui/environments/{name}`: its image, versions (each linked to its runs), registry entries, and every class it provides with its config and ports (`#Name` opens on one); administration, below | `list-environments`, `get-environment-manifest`, `list-environment-versions`, `list-simulators` |
| `/ui/environments/{name}/versions/{n}`: one version: its installed packages and a diff against another version, its lock and the pixi/uv files that recreate it, its entries with their compliance cases, its classes, and its runs | `get-environment-version`, `export-environment-version`, `get-environment-version-compliance` |
| `/ui/simulators/{id}`: one simulator (a container definition, identified by its hash): its definition, the versions it is, and its runs. A simulator from before versions belongs to no environment, and this page is the only place it is described | `get-simulator` |
| `/ui/catalog`: every registry entry with its curation level, pin and evidence, and the environments that run its classes ([plan-sedml.md](plan-sedml.md), "Concepts") | `list-registry-entries` |

**Viewers are registered per dataset type** (`webapp/app/viewers/registry.ts`, [plan](plan-viewers.md)). Each one
declares which datasets it fits (by kind, media type and attributes) and is an async component, so a viewer and its
libraries download only when first opened. `/ui/datasets/<id>` opens a dataset full width; the table's preview shows
the same viewers. Built in: composite (below), image, table (plotted when numeric), text, a Plotly figure (`application/vnd.plotly.v1+json`,
SED-ML plots), and for results bundles (`*.fenics`) a
statistics view and a **3D view** (vtk.js) read chunk by chunk with zarrita from `/datasets/{id}/files/`. The 3D view
draws the bundle's web extension (a precomputed surface per domain, viva-pde-particle `docs/web-bundle.md`) coloured by
one variable, fetches one row per frame, shows particles, and follows a running simulation.

**The submitted composite** (the `input` dataset: a `.pbg` document, or an OMEX archive holding one or more, found
as the service finds them at submission: `.pbg` and `.json` members, nested `.omex` archives at most three deep; with
several, a picker chooses one) opens in the composite viewer
(`webapp/app/viewers/CompositeViewer.vue`): the document is decompiled in the browser into `.pblang` text by
[process-bigraph-lang](https://github.com/biosimulations/process-bigraph-lang) (the npm package of its `dsl/`), checked, and shown read-only in Monaco with
the checker's findings as markers and as a list. The **Document** tab shows the process-bigraph JSON that was submitted
and run, re-indented only (every token as submitted: `100.0` stays a float), with a download; the **Graph** tab draws
the wiring (`viewers/composite/layout.ts`, stores left, processes and steps right, a link per wired port, nested
composites below). The checker resolves addresses against interface manifests: one per environment documents run in,
generated in CI inside each image and served by the API at `GET /registry/environments` and
`GET /registry/environments/{name}/manifest` (same origin; in development, from whatever `NUXT_PUBLIC_API_BASE` points
at). The viewer uses the manifest of the environment the run used (a prebuilt run is matched by its image's
repository, whatever its digest). Hovering a class's name in the text, or its `address` in the document, shows the
class's interface from that manifest (`viewers/composite/interfaces.ts`), linked to its environment's page; the
"checked against" badge links there too.

**Writing a composite** (`/ui/composites/new`, or "Edit a copy" from the viewer) opens `.pblang` text in an editable
Monaco with process-bigraph-lang's language server running in a web worker (`viewers/composite/languageClient.ts`):
findings appear as you type, hover shows a process's interface, and completion offers processes, ports, config keys
and stores, all from the manifest of the environment picked above the editor. **Run** compiles the text in the
browser (addresses in the `local:module.Class` form the service accepts; sidecar files compiled back in) and submits
the document as a `.pbg` to `/simulation/run` in that environment.

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

- Only API requests carry it: a request gets the token only when its destination is the API's own origin and path
  (`app/utils/apiAuth.ts`, after the platform's `isPlatformApiRequest`), never another host or a lookalike.
- When the API rejects it (401), the UI drops it, carries on anonymously, and shows a banner. It does not retry.
- When the session can no longer be renewed (the refresh token expired or was revoked), the UI signs the person out
  locally and says so, with a button to sign in again.
- Downloads by a signed-in user are fetched with the token, because a plain link cannot carry the header.
- After sign-in the UI asks `GET /auth/me` who the caller is, once. A token the API rejects shows up at once, and the
  account menu lists the roles the API sees.
- "Create account" opens Auth0's sign-up page. Signing in returns to the page the person started from.
- The account menu shows what the API says the caller may do (`capabilities` from `GET /auth/me`); with
  `environments:admin` it links "You can administer environments".

The token is kept in the browser's local storage, with rotating refresh tokens, as the platform frontend does
(decision D1 in [plan-webapp-login](plan-webapp-login.md)). Because script injection could read it, every `/ui`
response carries these security headers:

- A `Content-Security-Policy` that allows scripts only from this origin, plus the hashes of the build's inline
  scripts, which the API computes from the files it serves. Connections are allowed only to this origin and the Auth0
  tenant. The page cannot be framed. Production enforces it (`WEBAPP_CSP_ENFORCE=true`); without that setting it only reports. Browsers post violations
  to `POST /webapp/csp-report`, which the API logs as `CSP violation report`.
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.

A token changes nothing a caller can read, because every simulation is public. It changes what a caller may do
only through the capabilities below.

The SPA applications are created by auth0-pulumi (UCHHPC/auth0-pulumi#5): `p7uif3ex4LijqPwSOJsPBnhCdClnxSMM` for
production, whose callbacks also include the dev server's, and `fEbf0F5Orb6FD4TySB8yWSZTj5hhBNJV` for the local
cluster. Their ids are set in `kustomize/config/compose-api-rke/api.env` and
`kustomize/overlays/compose-api-local/auth0.env`.

## Administration

Environment versions are administered on the environment's own page ([plan-webapp-admin](plan-webapp-admin.md),
A2), not in a separate area. The controls appear only when `GET /auth/me` lists **`environments:admin`**, which a
caller has when they hold the deployment's `ENVIRONMENT_ADMIN_ROLE` (production: the tenant's `admin` role). The UI
only displays the capability: the API checks every request again and answers 403 to anyone else, so a hidden button
is never the protection.

| Action | Offered for | What it does |
|---|---|---|
| New version | a composed environment (`registry_env`, a mash-up) | resolves its registry entries as of a date (today: now) and locks them, then builds the image and runs its compliance cases; an identical lock gives the existing version |
| Register an image | a prebuilt environment | registers an image by digest (`repository@sha256:…`; tags are refused), pulls it and reads it back |
| Make default | a ready version that is not the default | runs that name no version run in it; recorded runs and suite runs, which name their versions, do not change |
| Retire | a ready or failed version that is not the default | it refuses new runs; recorded runs keep it, and its images are kept |
| Re-read contents | a ready version, or any prebuilt image | runs its image again, in the background, to record what it installed and the classes it provides; a build does this by itself, so it is for a prebuilt image or a record that is missing or wrong. Runs and the default are unaffected |

Every action is confirmed in a dialog that names the environment, the version and the effect (A3). Making a version
the default shows its packages against the current default's (`?against=`), since a new version changes nothing
until it is the default. After a new version is made, the page follows it every five seconds until it is ready or
failed, and shows why it failed. Custom library lists are not offered: that path is retired (composition D8.5).

The same actions are `compose-api environments create|default|retire|inspect` on the [command line](cli.md).

## Development

```bash
nvm use                   # Node 24: webapp/.nvmrc, linked from the repo root's .nvmrc (CI reads the same file)
make webapp-install       # npm ci
make run                  # the API on :8000
make webapp-dev           # the UI on http://localhost:4200/ui/, calling the API on :8000
COMPOSE_API_URL=https://compose.cam.uchc.edu make webapp-dev   # against production instead (CORS allows :4200)
make webapp-check         # lint, typecheck, API types current
make webapp-build         # static build; `make run` then serves it at http://localhost:8000/ui/
```

To sign in from the dev server against `make run`, set `AUTH0_AUDIENCE` and `AUTH0_SPA_CLIENT_ID` in `.dev_env` as
`.dev_env_TEMPLATE` describes: the production SPA is the only one whose callbacks include `http://localhost:4200/ui/`.

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
