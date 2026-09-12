from collections.abc import AsyncGenerator

import httpx
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from compose_api.api.client import Client
from compose_api.api.main import app


@pytest_asyncio.fixture(scope="function")
async def local_base_url() -> str:
    return "http://testserver"


@pytest_asyncio.fixture(scope="function")
async def fastapi_app() -> FastAPI:
    return app


@pytest_asyncio.fixture(scope="function")
async def http_api_client() -> AsyncGenerator[httpx.AsyncClient]:
    """A plain httpx client against the ASGI app, for asserting status codes.

    `in_memory_api_client` is the generated client with `raise_on_unexpected_status=True`,
    so it raises on any status the OpenAPI spec does not declare -- including a 404 that
    the server is correct to return. Use this fixture when the status code *is* the
    assertion; use the generated client when the parsed model is.
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def in_memory_api_client() -> AsyncGenerator[Client]:
    transport = ASGITransport(app=app)
    async_client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client = Client(base_url="http://testserver", raise_on_unexpected_status=True)
    client.set_async_httpx_client(async_client)
    yield client
    await async_client.aclose()
