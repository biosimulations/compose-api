"""The catalog of registry entries, the environments this service runs documents in, and the process interfaces each
one provides (docs/plan-sedml.md, "Concepts": the catalog is discovery and trust, an environment is execution).

The web app's composite editor and viewer check `.pblang` text against the manifest of the environment the document
runs in (docs/plan-authoring.md). The manifests are generated in CI inside each environment's image and ship with
this service (compose_api/registry/manifests/); see compose_api/registry/environments.py.
"""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from compose_api.authentication import OptionalPrincipal, get_optional_principal
from compose_api.common.gateway.models import RouterConfig
from compose_api.registry.environments import (
    CatalogEntry,
    EnvironmentSummary,
    InterfaceManifest,
    catalog_entries,
    load_environments,
    manifest_path,
    read_manifest,
    summarize,
)
from compose_api.registry.solvers import Solver, load_solvers

config = RouterConfig(router=APIRouter(), prefix="/registry", dependencies=[Depends(get_optional_principal)])


@config.router.get(
    path="/environments",
    response_model=list[EnvironmentSummary],
    operation_id="list-environments",
    tags=["Registry"],
    summary="The environments documents run in, with what their interface manifests hold",
)
async def list_environments(principal: OptionalPrincipal) -> list[EnvironmentSummary]:
    # public: the same for every caller
    return [s for s in (summarize(spec) for spec in load_environments().environments) if s is not None]


@config.router.get(
    path="/environments/{name}/manifest",
    response_model=InterfaceManifest,
    operation_id="get-environment-manifest",
    tags=["Registry"],
    summary="An environment's interface manifest (pbg-interfaces/1), each component with its registry entry",
    responses={404: {"description": "No such environment here, or no manifest has been generated for it"}},
)
async def get_environment_manifest(
    name: str, request: Request, response: Response, principal: OptionalPrincipal
) -> InterfaceManifest | Response:
    # public: the same for every caller
    spec = next((e for e in load_environments().environments if e.name == name), None)
    if spec is None or summarize(spec) is None:
        raise HTTPException(status_code=404, detail=f"no environment {name!r}")
    path = manifest_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no interface manifest has been generated for {name!r}")
    etag = '"' + hashlib.sha256(path.read_bytes()).hexdigest()[:32] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    manifest = read_manifest(name)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"no interface manifest has been generated for {name!r}")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return manifest


@config.router.get(
    path="/entries",
    response_model=list[CatalogEntry],
    operation_id="list-registry-entries",
    tags=["Registry"],
    summary="The catalog: every registry entry with its curation level, pin and evidence, and the environments that "
    "provide its classes",
)
async def list_registry_entries(principal: OptionalPrincipal) -> list[CatalogEntry]:
    # public: the same for every caller
    return catalog_entries()


@config.router.get(
    path="/solvers",
    response_model=list[Solver],
    operation_id="list-solvers",
    tags=["Registry"],
    summary="The solvers SED-ML runs can use: each one's class, environment, KiSAO algorithms and what it returns",
)
async def list_solvers(principal: OptionalPrincipal) -> list[Solver]:
    # public: the same for every caller
    return list(load_solvers().solvers)
