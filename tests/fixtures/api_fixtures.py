from collections.abc import AsyncGenerator

import httpx
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from biosim_api.api.client import Client
from biosim_api.api.main import app


@pytest_asyncio.fixture(scope="function")
async def local_base_url() -> str:
    return "http://testserver"


@pytest_asyncio.fixture(scope="function")
async def fastapi_app() -> FastAPI:
    return app


@pytest_asyncio.fixture(scope="function")
async def in_memory_api_client() -> AsyncGenerator[Client, None]:
    transport = ASGITransport(app=app)
    async_client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client = Client(base_url="http://testserver", raise_on_unexpected_status=True)
    client.set_async_httpx_client(async_client)
    yield client
    await async_client.aclose()
