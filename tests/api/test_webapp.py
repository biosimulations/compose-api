import base64
import hashlib
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from compose_api.api.main import app as main_app
from compose_api.api.webapp import (
    MAX_CSP_REPORT_BYTES,
    SPA_FALLBACK,
    content_security_policy,
    inline_script_hashes,
    mount_webapp,
)
from compose_api.config import get_settings, override_settings
from compose_api.db.database_service import DatabaseService
from compose_api.observability.datasets import DATASET_KINDS
from tests.fixtures.postgres_fixtures import register_prebuilt

SHELL = "<html>spa shell</html>"


@pytest_asyncio.fixture
async def webapp_client(tmp_path: Path) -> AsyncGenerator[httpx.AsyncClient]:
    (tmp_path / SPA_FALLBACK).write_text(SHELL)
    (tmp_path / "index.html").write_text(SHELL)
    (tmp_path / "_nuxt").mkdir()
    (tmp_path / "_nuxt" / "entry.js").write_text("console.log(1)")
    app = FastAPI()
    assert mount_webapp(app, tmp_path)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_root_redirects_to_the_webapp(webapp_client: httpx.AsyncClient) -> None:
    for path in ("/", "/ui"):
        response = await webapp_client.get(path)
        assert response.status_code == 307
        assert response.headers["location"] == "/ui/"


@pytest.mark.asyncio
async def test_webapp_serves_files_and_the_shell_for_client_routes(webapp_client: httpx.AsyncClient) -> None:
    assert (await webapp_client.get("/ui/")).text == SHELL
    assert (await webapp_client.get("/ui/_nuxt/entry.js")).text == "console.log(1)"
    # A deep link the client router owns loads the app instead of a 404.
    deep = await webapp_client.get("/ui/simulations/5")
    assert deep.status_code == 200
    assert deep.text == SHELL


@pytest.mark.asyncio
async def test_missing_asset_is_still_404(webapp_client: httpx.AsyncClient) -> None:
    assert (await webapp_client.get("/ui/_nuxt/missing.js")).status_code == 404


def test_without_a_build_only_the_config_and_report_endpoints_are_added(tmp_path: Path) -> None:
    app = FastAPI()
    assert not mount_webapp(app, tmp_path / "absent")
    assert [getattr(r, "path", None) for r in app.routes][-2:] == ["/webapp/config", "/webapp/csp-report"]


@pytest.mark.asyncio
async def test_webapp_config_publishes_login_settings_and_simulator_names(
    http_api_client: httpx.AsyncClient, database_service: DatabaseService
) -> None:
    """The prebuilt environments a run may name: those with a registered default version (D8.3)."""
    await register_prebuilt(database_service, "viva-pde-particle", "ghcr.io/example/pde@sha256:" + "2" * 64)
    with override_settings(auth0_spa_client_id="spa-client"):
        response = await http_api_client.get("/webapp/config")
    assert response.status_code == 200
    assert response.json() == {
        "auth0_domain": get_settings().auth0_domain,
        "auth0_audience": get_settings().auth0_audience,
        "auth0_client_id": "spa-client",
        "prebuilt_simulators": ["viva-pde-particle"],
        "dataset_kinds": DATASET_KINDS,
    }
    assert "results-bundle" in DATASET_KINDS
    assert "file" in DATASET_KINDS


def test_webapp_routes_are_not_api_operations() -> None:
    paths = main_app.openapi()["paths"]
    assert "/webapp/config" not in paths
    assert "/webapp/csp-report" not in paths
    assert "/" not in paths


INLINE = "window.__NUXT__={};"
PAGE = (
    '<html><script type="importmap">{"imports":{}}</script><script type="module" src="/ui/_nuxt/e.js"></script>'
    f'<script>{INLINE}</script><script type="application/json" id="__NUXT_DATA__">[1]</script></html>'
)


def test_inline_scripts_are_hashed_and_data_blocks_are_not(tmp_path: Path) -> None:
    (tmp_path / SPA_FALLBACK).write_text(PAGE)
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "index.html").write_text(f"<script>{INLINE}</script>")
    hashes = inline_script_hashes(tmp_path)
    expected = {
        "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
        for body in ('{"imports":{}}', INLINE)
    }
    assert set(hashes) == expected  # the import map and the config script, each once; not the src or JSON ones


def test_the_policy_names_only_this_origin_and_the_tenant() -> None:
    policy = dict(
        part.split(" ", 1) for part in content_security_policy("tenant.auth0.com", ["'sha256-x'"]).split("; ")
    )
    assert policy["script-src"] == "'self' 'sha256-x'"
    assert policy["connect-src"] == "'self' https://tenant.auth0.com"
    assert policy["frame-src"] == "https://tenant.auth0.com"
    assert policy["frame-ancestors"] == "'none'"
    assert policy["object-src"] == "'none'"
    assert policy["report-uri"] == "/webapp/csp-report"
    # Without a tenant there is nothing to sign in with, and nothing to frame.
    assert content_security_policy("", []).count("https://") == 0


@pytest.mark.asyncio
async def test_every_ui_response_carries_the_security_headers(webapp_client: httpx.AsyncClient) -> None:
    for path in ("/ui/", "/ui/simulations/5", "/ui/_nuxt/entry.js"):
        headers = (await webapp_client.get(path)).headers
        assert "script-src 'self'" in headers["content-security-policy-report-only"], path
        assert "content-security-policy" not in headers, path
        assert headers["x-frame-options"] == "DENY"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
    with override_settings(webapp_csp_enforce=True):
        headers = (await webapp_client.get("/ui/")).headers
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "content-security-policy-report-only" not in headers


@pytest.mark.asyncio
async def test_csp_reports_are_accepted_and_capped(
    webapp_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    report = '{"csp-report":{"violated-directive":"script-src","blocked-uri":"inline"}}'
    response = await webapp_client.post(
        "/webapp/csp-report", content=report, headers={"content-type": "application/csp-report"}
    )
    assert response.status_code == 204
    assert "violated-directive" in caplog.text
    caplog.clear()
    huge = await webapp_client.post("/webapp/csp-report", content=b"x" * (MAX_CSP_REPORT_BYTES * 4))
    assert huge.status_code == 204
    logged = next(r.getMessage() for r in caplog.records if "CSP violation" in r.getMessage())
    assert len(logged) < MAX_CSP_REPORT_BYTES + 100
