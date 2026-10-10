from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from compose_api.api.main import app as main_app
from compose_api.api.webapp import SPA_FALLBACK, mount_webapp
from compose_api.config import get_settings, override_settings
from compose_api.observability.datasets import DATASET_KINDS

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


def test_without_a_build_only_the_config_endpoint_is_added(tmp_path: Path) -> None:
    app = FastAPI()
    assert not mount_webapp(app, tmp_path / "absent")
    assert [getattr(r, "path", None) for r in app.routes][-1] == "/webapp/config"


@pytest.mark.asyncio
async def test_webapp_config_publishes_login_settings_and_simulator_names(
    http_api_client: httpx.AsyncClient,
) -> None:
    with override_settings(auth0_spa_client_id="spa-client", prebuilt_simulators={"b-sim": "img:b", "a-sim": "img:a"}):
        response = await http_api_client.get("/webapp/config")
    assert response.status_code == 200
    assert response.json() == {
        "auth0_domain": get_settings().auth0_domain,
        "auth0_audience": get_settings().auth0_audience,
        "auth0_client_id": "spa-client",
        "prebuilt_simulators": ["a-sim", "b-sim"],
        "dataset_kinds": DATASET_KINDS,
    }
    assert "results-bundle" in DATASET_KINDS
    assert "file" in DATASET_KINDS


def test_webapp_routes_are_not_api_operations() -> None:
    paths = main_app.openapi()["paths"]
    assert "/webapp/config" not in paths
    assert "/" not in paths
