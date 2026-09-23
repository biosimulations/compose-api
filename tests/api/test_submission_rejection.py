"""/simulation/run refuses what the registry does not allow, with a 400 that names each address (goal G6).

Rejection happens before any service is consulted, so these need no database, scheduler or cluster.
"""

import json

import httpx
import pytest

from compose_api.config import override_settings


def pbg(*addresses: str) -> bytes:
    return json.dumps({"state": {f"s{i}": {"_type": "step", "address": a} for i, a in enumerate(addresses)}}).encode()


@pytest.mark.asyncio
async def test_unregistered_and_unsafe_addresses_are_a_400_listing_each(http_api_client: httpx.AsyncClient) -> None:
    response = await http_api_client.post(
        "/simulation/run",
        files={"uploaded_file": ("doc.pbg", pbg("local:numpy.Solver", "local:!os.system"), "application/json")},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert {v["address"] for v in detail["violations"]} == {"local:numpy.Solver", "local:!os.system"}


@pytest.mark.asyncio
async def test_warn_policy_still_refuses_unsafe_forms(http_api_client: httpx.AsyncClient) -> None:
    with override_settings(address_policy="warn"):
        response = await http_api_client.post(
            "/simulation/run",
            files={"uploaded_file": ("doc.pbg", pbg("rest:http://example.org/p"), "application/json")},
        )
    assert response.status_code == 400
    assert response.json()["detail"]["violations"][0]["always_rejected"] is True


@pytest.mark.asyncio
async def test_unreadable_archive_is_a_400(http_api_client: httpx.AsyncClient) -> None:
    response = await http_api_client.post(
        "/simulation/run", files={"uploaded_file": ("x.omex", b"not a zip", "application/zip")}
    )
    assert response.status_code == 400
    assert "not a valid OMEX" in response.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_unknown_file_type_is_a_400_not_a_500(http_api_client: httpx.AsyncClient) -> None:
    response = await http_api_client.post(
        "/simulation/run", files={"uploaded_file": ("model.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.text
