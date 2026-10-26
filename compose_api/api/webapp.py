"""The web UI: a static Nuxt SPA (``webapp/``) served at ``/ui``, and the settings it reads at ``GET /webapp/config``.

The SPA is built with ``nuxt generate`` into ``settings.webapp_dist_dir`` (the image builds it, see Dockerfile-api).
Without a build, the API starts as before and only the config endpoint exists. Both routes are left out of the
OpenAPI schema: they are not API operations, so the generated client and the CLI do not see them.
"""

import base64
import hashlib
import logging
import re
from pathlib import Path

from fastapi import FastAPI, Request
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import RedirectResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from compose_api.config import get_settings
from compose_api.observability.datasets import DATASET_KINDS

logger = logging.getLogger(__name__)

WEBAPP_PATH = "/ui"
# nuxt generate writes this shell for client-side routes it did not prerender.
SPA_FALLBACK = "200.html"
CSP_REPORT_PATH = "/webapp/csp-report"
MAX_CSP_REPORT_BYTES = 16 * 1024

# An inline script the browser executes (not a data block such as Nuxt's JSON payload), and its body.
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)
_DATA_BLOCK = re.compile(r"""\btype=["']?application/(?:ld\+)?json""", re.IGNORECASE)


class WebappConfig(BaseModel):
    """What the SPA cannot know at build time. Login is offered only when all three Auth0 values are set."""

    auth0_domain: str
    auth0_audience: str
    auth0_client_id: str
    prebuilt_simulators: list[str]
    # The kinds the API infers from file names, for the datasets filter; a simulator may announce others.
    dataset_kinds: list[str]


def inline_script_hashes(dist_dir: Path) -> list[str]:
    """The CSP source for every inline script in the build's pages (`'sha256-...'`), sorted.

    nuxt generate writes three inline scripts into each page: the import map, the colour-mode bootstrap and the
    runtime config. The runtime config includes the build id, so its hash changes with every build. Hashing the files
    the API actually serves keeps the policy in step without a nonce, which a static build cannot carry.
    """
    hashes: set[str] = set()
    for page in dist_dir.rglob("*.html"):
        for attributes, body in _INLINE_SCRIPT.findall(page.read_text(encoding="utf-8", errors="replace")):
            if _DATA_BLOCK.search(attributes) or not body.strip():
                continue
            digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
            hashes.add(f"'sha256-{digest}'")
    return sorted(hashes)


def content_security_policy(auth0_domain: str, script_hashes: list[str]) -> str:
    """The policy for the UI's pages: its own origin, plus the Auth0 tenant it signs in with.

    Styles keep 'unsafe-inline': Vue's style bindings and Plotly write inline styles, and a stylesheet cannot run code.
    """
    tenant = f" https://{auth0_domain}" if auth0_domain else ""
    directives = {
        "default-src": "'self'",
        "script-src": " ".join(["'self'", *script_hashes]),
        "style-src": "'self' 'unsafe-inline'",
        "img-src": "'self' data: blob: https:",  # profile pictures come from the identity provider's hosts
        "font-src": "'self' data:",
        "connect-src": f"'self'{tenant}",
        "frame-src": tenant.strip() or "'none'",
        "worker-src": "'self' blob:",
        "object-src": "'none'",
        "base-uri": "'self'",
        "form-action": "'self'",
        "frame-ancestors": "'none'",
        "report-uri": CSP_REPORT_PATH,
    }
    return "; ".join(f"{name} {value}" for name, value in directives.items())


class SpaStaticFiles(StaticFiles):
    """Static files, with any unknown route that is not a file (no suffix) answered by the SPA shell, so a deep
    link such as /ui/simulations/5 loads the app and the client router resolves it. Every response carries the UI's
    security headers: the Content-Security-Policy (report-only until `webapp_csp_enforce`), no framing, no MIME
    sniffing and no referrer, since the app keeps its sign-in tokens in the page's storage."""

    def __init__(self, *, directory: Path, script_hashes: list[str]) -> None:
        super().__init__(directory=directory)
        self.script_hashes = script_hashes

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404 or Path(path).suffix:
                raise
            response = await super().get_response(SPA_FALLBACK, scope)
        settings = get_settings()
        policy_header = (
            "Content-Security-Policy" if settings.webapp_csp_enforce else "Content-Security-Policy-Report-Only"
        )
        response.headers[policy_header] = content_security_policy(settings.auth0_domain, self.script_hashes)
        response.headers["X-Frame-Options"] = "DENY"  # frame-ancestors is not enforced while the policy only reports
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


async def receive_csp_report(request: Request) -> Response:
    """Log a browser's Content-Security-Policy violation report, so the policy can be measured before it is enforced.

    Anyone can post here, so the body is capped and only logged, never parsed into anything else.
    """
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) >= MAX_CSP_REPORT_BYTES:
            break  # stop reading: a report is a few hundred bytes
    logger.warning("CSP violation report: %s", body[:MAX_CSP_REPORT_BYTES].decode("utf-8", errors="replace"))
    return Response(status_code=204)


async def get_webapp_config() -> WebappConfig:
    from compose_api.dependencies import get_database_service  # late: dependencies imports the API modules
    from compose_api.environments.versions import prebuilt_images

    settings = get_settings()
    return WebappConfig(
        auth0_domain=settings.auth0_domain,
        auth0_audience=settings.auth0_audience,
        auth0_client_id=settings.auth0_spa_client_id,
        # the prebuilt environments a run may name: those with a default version (D8.3)
        prebuilt_simulators=sorted(await prebuilt_images(get_database_service())),
        dataset_kinds=DATASET_KINDS,
    )


def mount_webapp(app: FastAPI, dist_dir: Path) -> bool:
    """Add the config endpoint and, when ``dist_dir`` holds a build, serve it at /ui with / redirecting there."""
    app.add_api_route("/webapp/config", get_webapp_config, methods=["GET"], include_in_schema=False)
    app.add_api_route(CSP_REPORT_PATH, receive_csp_report, methods=["POST"], include_in_schema=False)
    if not (dist_dir / SPA_FALLBACK).is_file():
        return False

    async def to_webapp() -> RedirectResponse:
        return RedirectResponse(f"{WEBAPP_PATH}/")

    app.add_api_route("/", to_webapp, methods=["GET"], include_in_schema=False)
    app.add_api_route(WEBAPP_PATH, to_webapp, methods=["GET"], include_in_schema=False)
    hashes = inline_script_hashes(dist_dir)
    app.mount(WEBAPP_PATH, SpaStaticFiles(directory=dist_dir, script_hashes=hashes), name="webapp")
    return True
