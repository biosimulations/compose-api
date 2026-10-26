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


@pytest.mark.asyncio
async def test_a_listed_prebuilt_simulator_is_not_checked_against_the_registry(
    http_api_client: httpx.AsyncClient,
) -> None:
    """Its image brings its own processes; the deployment vouches for the image by listing it."""
    with override_settings(prebuilt_simulators={"sim-a": "ghcr.io/example/simulator@sha256:" + "0" * 64}):
        response = await http_api_client.post(
            "/simulation/run",
            params={"simulator": "sim-a"},
            files={"uploaded_file": ("doc.pbg", pbg("local:sim_a.processes.Solver"), "application/json")},
        )
    assert not (response.status_code == 400 and "violations" in response.text), response.text


@pytest.mark.asyncio
async def test_a_listed_prebuilt_simulator_still_refuses_unsafe_forms(http_api_client: httpx.AsyncClient) -> None:
    """Listing the image vouches for its classes, not for an arbitrary import or another protocol."""
    with override_settings(prebuilt_simulators={"sim-a": "ghcr.io/example/simulator@sha256:" + "0" * 64}):
        response = await http_api_client.post(
            "/simulation/run",
            params={"simulator": "sim-a"},
            files={
                "uploaded_file": (
                    "doc.pbg",
                    pbg("local:sim_a.processes.Solver", "local:!os.system", "rest:http://example.org/p"),
                    "application/json",
                )
            },
        )
    assert response.status_code == 400
    violations = response.json()["detail"]["violations"]
    assert {v["address"] for v in violations} == {"local:!os.system", "rest:http://example.org/p"}
    assert all(v["always_rejected"] for v in violations)


@pytest.mark.asyncio
async def test_an_unlisted_simulator_is_refused_before_the_registry(http_api_client: httpx.AsyncClient) -> None:
    with override_settings(prebuilt_simulators={}):
        response = await http_api_client.post(
            "/simulation/run",
            params={"simulator": "sim-a"},
            files={"uploaded_file": ("doc.pbg", pbg("local:sim_a.processes.Solver"), "application/json")},
        )
    assert response.status_code == 400
    assert "unknown simulator" in response.json()["detail"]


@pytest.mark.asyncio
async def test_a_malformed_tag_or_overlong_description_is_a_400(http_api_client: httpx.AsyncClient) -> None:
    files = {"uploaded_file": ("doc.pbg", pbg(), "application/json")}
    bad_tag = await http_api_client.post("/simulation/run", files=files, params={"tags": ["ok", "-starts-badly"]})
    assert bad_tag.status_code == 400 and "-starts-badly" in bad_tag.json()["detail"]
    long = await http_api_client.post("/simulation/run", files=files, params={"description": "x" * 2001})
    assert long.status_code == 400 and "description" in long.json()["detail"]


PDE_IMAGE = "ghcr.io/example/pde@sha256:" + "1" * 64
PDE = "local:viva_pde_particle.processes.fenicsx_reaction_diffusion.FenicsxReactionDiffusion"


@pytest.mark.asyncio
async def test_a_run_naming_no_environment_goes_where_its_classes_are(http_api_client: httpx.AsyncClient) -> None:
    """Step 7a (D7.1): a document using only viva-pde-particle's classes is inferred to run in its image when the
    deployment offers it, as if it had named it; offered nowhere, the shared environment refuses it as before."""
    with override_settings(prebuilt_simulators={"viva-pde-particle": PDE_IMAGE}):
        inferred = await http_api_client.post(
            "/simulation/run", files={"uploaded_file": ("doc.pbg", pbg(PDE), "application/json")}
        )
    assert not (inferred.status_code == 400 and "violations" in inferred.text), inferred.text
    with override_settings(prebuilt_simulators={}):
        refused = await http_api_client.post(
            "/simulation/run", files={"uploaded_file": ("doc.pbg", pbg(PDE), "application/json")}
        )
    assert refused.status_code == 400
    (violation,) = refused.json()["detail"]["violations"]
    assert "not installed in the environment `registry_env`" in violation["reason"]


@pytest.mark.asyncio
async def test_a_named_environment_is_used_as_given(http_api_client: httpx.AsyncClient) -> None:
    """`environment=` names any offered environment; the shared one checks the registry, whatever was inferable."""
    with override_settings(prebuilt_simulators={"viva-pde-particle": PDE_IMAGE}):
        shared = await http_api_client.post(
            "/simulation/run",
            params={"environment": "registry_env"},
            files={"uploaded_file": ("doc.pbg", pbg(PDE), "application/json")},
        )
        disagreeing = await http_api_client.post(
            "/simulation/run",
            params={"environment": "registry_env", "simulator": "viva-pde-particle"},
            files={"uploaded_file": ("doc.pbg", pbg(PDE), "application/json")},
        )
        unknown = await http_api_client.post(
            "/simulation/run",
            params={"environment": "nowhere"},
            files={"uploaded_file": ("doc.pbg", pbg(PDE), "application/json")},
        )
    assert shared.status_code == 400 and "registry_env" in shared.json()["detail"]["violations"][0]["reason"]
    assert disagreeing.status_code == 400 and "disagree" in disagreeing.json()["detail"]
    assert unknown.status_code == 400 and "No environment 'nowhere'" in unknown.json()["detail"]
