"""The web UI: a static Nuxt SPA (``webapp/``) served at ``/ui``, and the settings it reads at ``GET /webapp/config``.

The SPA is built with ``nuxt generate`` into ``settings.webapp_dist_dir`` (the image builds it, see Dockerfile-api).
Without a build, the API starts as before and only the config endpoint exists. Both routes are left out of the
OpenAPI schema: they are not API operations, so the generated client and the CLI do not see them.
"""

from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import RedirectResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from compose_api.config import get_settings
from compose_api.observability.datasets import DATASET_KINDS

WEBAPP_PATH = "/ui"
# nuxt generate writes this shell for client-side routes it did not prerender.
SPA_FALLBACK = "200.html"


class WebappConfig(BaseModel):
    """What the SPA cannot know at build time. Login is offered only when all three Auth0 values are set."""

    auth0_domain: str
    auth0_audience: str
    auth0_client_id: str
    prebuilt_simulators: list[str]
    # The kinds the API infers from file names, for the datasets filter; a simulator may announce others.
    dataset_kinds: list[str]


class SpaStaticFiles(StaticFiles):
    """Static files, with any unknown route that is not a file (no suffix) answered by the SPA shell, so a deep
    link such as /ui/simulations/5 loads the app and the client router resolves it."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404 or Path(path).suffix:
                raise
            return await super().get_response(SPA_FALLBACK, scope)


async def get_webapp_config() -> WebappConfig:
    settings = get_settings()
    return WebappConfig(
        auth0_domain=settings.auth0_domain,
        auth0_audience=settings.auth0_audience,
        auth0_client_id=settings.auth0_spa_client_id,
        prebuilt_simulators=sorted(settings.prebuilt_simulators),
        dataset_kinds=DATASET_KINDS,
    )


def mount_webapp(app: FastAPI, dist_dir: Path) -> bool:
    """Add the config endpoint and, when ``dist_dir`` holds a build, serve it at /ui with / redirecting there."""
    app.add_api_route("/webapp/config", get_webapp_config, methods=["GET"], include_in_schema=False)
    if not (dist_dir / SPA_FALLBACK).is_file():
        return False

    async def to_webapp() -> RedirectResponse:
        return RedirectResponse(f"{WEBAPP_PATH}/")

    app.add_api_route("/", to_webapp, methods=["GET"], include_in_schema=False)
    app.add_api_route(WEBAPP_PATH, to_webapp, methods=["GET"], include_in_schema=False)
    app.mount(WEBAPP_PATH, SpaStaticFiles(directory=dist_dir), name="webapp")
    return True
